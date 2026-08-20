"""End-to-end regression for final-rereview N1, through the real tracer
and a real `patch.py` run rather than a hand-built trace dict.

`tests/test_guard_multi_path.py` pins the exact wording at several counts
by constructing the trace JSON directly; this file exists to prove the
same honesty holds when `trace.py` itself is the one doing the capping,
and that the resulting multi-line guard block still survives `patch.py`'s
marker check and `git apply` for real.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import artifacts
import patch
import trace as tracer


class TestCappedTestPathsGuardLine(unittest.TestCase):
    """One commit touches the target plus 30 test-looking paths; trace()
    is run with `max_co_changed=5`, so `co_changed` keeps only the first
    5 while `co_changed_totals` still records the true count of 30."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_guard_capped_test_paths(self.tmp.name, n=30)
        self.result = tracer.trace(
            self.info["repo"], self.info["path"], self.info["line"], self.info["line"],
            max_co_changed=5,
        )

    def test_premise_the_cap_actually_cut_the_list(self):
        # Pin the shape the finding depends on: 30 test-looking paths
        # touched, only 5 survive trace.py's per-commit cap.
        sha = self.info["sha"]
        self.assertEqual(self.result["co_changed_totals"][sha], 30)
        present = [c for c in self.result["co_changed"] if c["sha"] == sha]
        self.assertEqual(len(present), 5)

    def test_guard_line_says_at_least_not_an_exact_undercount(self):
        # 5 shown, 3 named (_MAX_NAMED_GUARDS), so the tail describes 2 --
        # but 25 more test-looking paths exist beyond what the cap let
        # through, so "and 2 more" would undercount them; "and at least 2
        # more" is what the data can support.
        out = artifacts.skeleton("danger", self.result)
        lines = out.splitlines()
        self.assertIn("#   and at least 2 more", lines)
        self.assertNotIn("#   and 2 more", lines)

    def test_named_paths_are_the_first_three_alphabetically(self):
        out = artifacts.skeleton("danger", self.result)
        lines = out.splitlines()
        for i in (1, 2, 3):
            self.assertIn("#   t/case_{:02d}_test.py".format(i), lines)
        self.assertNotIn("#   t/case_04_test.py", lines)

    def test_real_patch_applies_and_every_added_line_carries_the_marker(self):
        verdict_data = {
            "grade": "danger",
            "summary": "This guard prevents a double charge.",
            "evidence": [{"type": "commit", "ref": self.info["sha"], "role": "introduced"}],
        }
        diff = patch.build(self.result, verdict_data, repo=self.info["repo"])

        target_full = Path(self.info["repo"]) / self.info["path"]
        before = target_full.read_text().split("\n")

        patch_file = Path(self.info["repo"]) / "keep.patch"
        patch_file.write_text(diff)
        applied = subprocess.run(["git", "apply", "keep.patch"],
                                  cwd=self.info["repo"], capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0,
                          "git apply rejected the patch: " + applied.stderr)

        after = target_full.read_text().split("\n")
        at = self.info["line"] - 1  # 0-based index of the target line
        inserted = len(after) - len(before)
        self.assertGreaterEqual(inserted, 1, "nothing was inserted")
        self.assertEqual(after[:at], before[:at])
        self.assertEqual(after[at + inserted:], before[at:])

        added = after[at:at + inserted]
        self.assertGreater(len(added), 1)
        for line in added:
            self.assertTrue(line.startswith("    # "),
                            "not an indented comment: " + repr(line))

        longest = max(len(l) for l in added)
        # Not a correctness bound (see final-rereview's N4), just keeping
        # this observable: report the longest line this real run produced.
        print("\nlongest inserted line ({} chars): {!r}".format(longest,
              max(added, key=len)))


class TestCappedTestPathsExtraZero(unittest.TestCase):
    """The N1 fix's own boundary: `max_co_changed=3` against the same 30
    test-looking paths leaves exactly `_MAX_NAMED_GUARDS` (3) entries in
    `co_changed`, so every one of them gets named and `extra` is 0 -- but
    27 more files this commit touched were never even considered, and the
    guard block has to say so rather than fall silent just because the
    remainder count happens to be 0."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_guard_capped_test_paths(self.tmp.name, n=30)
        self.result = tracer.trace(
            self.info["repo"], self.info["path"], self.info["line"], self.info["line"],
            max_co_changed=3,
        )

    def test_premise_every_shown_path_is_named_none_left_over(self):
        sha = self.info["sha"]
        self.assertEqual(self.result["co_changed_totals"][sha], 30)
        present = [c for c in self.result["co_changed"] if c["sha"] == sha]
        self.assertEqual(len(present), 3)

    def test_guard_block_discloses_the_list_cut_not_silence(self):
        out = artifacts.skeleton("danger", self.result)
        lines = out.splitlines()
        self.assertIn(
            "#   and possibly more: 3 of 30 files from this commit are listed",
            lines,
        )

    def test_real_patch_still_applies_with_the_disclosure_line(self):
        verdict_data = {
            "grade": "danger",
            "summary": "This guard prevents a double charge.",
            "evidence": [{"type": "commit", "ref": self.info["sha"], "role": "introduced"}],
        }
        diff = patch.build(self.result, verdict_data, repo=self.info["repo"])
        self.assertIn(
            "+    #   and possibly more: 3 of 30 files from this commit are listed",
            diff.splitlines(),
        )

        patch_file = Path(self.info["repo"]) / "keep.patch"
        patch_file.write_text(diff)
        applied = subprocess.run(["git", "apply", "--check", "keep.patch"],
                                  cwd=self.info["repo"], capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0,
                          "git apply rejected the patch: " + applied.stderr)


if __name__ == "__main__":
    unittest.main()
