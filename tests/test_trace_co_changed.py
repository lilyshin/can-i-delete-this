"""Regression tests for trace()'s co_changed cap.

Before this cap existed, a single commit that touched hundreds of paths (a
vendor bump, a monorepo-wide rename) dumped its entire file list into
co_changed, and that field ended up dominating the whole trace JSON.
trace.CO_CHANGED_PER_COMMIT bounds how many paths survive per commit,
ranked by priority (a co-changed test outranks everything, then a file
beside the target, then everything else), with the true per-commit count
still recorded in co_changed_totals so the cut is disclosed rather than
made to look like a complete list.

make_fixture_repo.build_co_changed_cap builds two commits for this:
big_sha changes the target plus six other paths (one test file, two
same-directory files, three unrelated ones); base_sha changes the target
plus exactly one other path, fewer than any cap used below, to prove an
under-cap commit is carried whole. Both are threaded into trace() via
include_commits so this file does not have to also exercise blame/pickaxe
discovery, only what co_changed does with each commit's changed paths.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import noise
import trace as tracer

_SCRIPT = str(
    Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts" / "trace.py"
)


def _trace_co_changed(info, max_co_changed):
    return tracer.trace(
        info["repo"], info["path"], info["line"], info["line"],
        include_commits=[info["big_sha"], info["base_sha"]],
        max_co_changed=max_co_changed,
    )


class TestCapKeepsHighestPriorityPaths(unittest.TestCase):
    """A mutation that deletes the cap (keeping every changed path) turns
    this red: len(big_entries) would be 6, not 3.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_co_changed_cap(self.tmp.name)

    def test_cap_of_three_keeps_exactly_three_entries(self):
        result = _trace_co_changed(self.info, max_co_changed=3)
        big_entries = [c for c in result["co_changed"] if c["sha"] == self.info["big_sha"]]
        self.assertEqual(len(big_entries), 3)

    def test_test_file_survives_the_cap_despite_many_far_files(self):
        # A mutation that deletes the priority ordering (falling back to
        # git's raw order, or to an unranked cut) turns this red: the test
        # file is last in git's own changed-paths order (see the fixture's
        # docstring), so an unranked cap would drop it in favor of the
        # far-directory files that precede it.
        result = _trace_co_changed(self.info, max_co_changed=3)
        big_paths = [c["path"] for c in result["co_changed"] if c["sha"] == self.info["big_sha"]]
        self.assertIn(self.info["test_path"], big_paths)

    def test_same_directory_files_rank_before_far_files(self):
        # A cap of 4 leaves room for exactly one path past the test file
        # and the two same-directory files; a mutation that deletes the
        # priority ordering (or reverses the same-dir/far tiers) turns this
        # red, either by admitting a far file before both same-dir files
        # or by admitting no far file where one is expected.
        result = _trace_co_changed(self.info, max_co_changed=4)
        big_paths = [c["path"] for c in result["co_changed"] if c["sha"] == self.info["big_sha"]]
        self.assertEqual(len(big_paths), 4)
        same_dir = self.info["same_dir_paths"]
        far = self.info["far_paths"]
        same_dir_positions = [big_paths.index(p) for p in same_dir if p in big_paths]
        far_positions = [big_paths.index(p) for p in far if p in big_paths]
        self.assertEqual(len(far_positions), 1)
        self.assertTrue(max(same_dir_positions) < far_positions[0])

    def test_totals_reflect_the_true_precap_count(self):
        result = _trace_co_changed(self.info, max_co_changed=3)
        self.assertEqual(
            result["co_changed_totals"][self.info["big_sha"]], self.info["big_total"])

    def test_target_itself_excluded_from_co_changed_and_totals(self):
        result = _trace_co_changed(self.info, max_co_changed=3)
        all_paths = [c["path"] for c in result["co_changed"]]
        self.assertNotIn(self.info["path"], all_paths)
        # If the target leaked into the raw changed-paths count, big_total
        # (6) would be off by one; info["big_total"] already excludes it,
        # and the assertion above pins that trace() agrees.
        self.assertEqual(
            result["co_changed_totals"][self.info["big_sha"]], self.info["big_total"])

    def test_under_cap_commit_is_kept_whole(self):
        # base_sha changes exactly one path besides the target, fewer than
        # any cap this test module uses. A mutation that clips every
        # commit's list uniformly rather than only the ones over the cap
        # turns this red: base_sha's single entry would come out truncated
        # (0 entries) instead of the 1 it actually has.
        result = _trace_co_changed(self.info, max_co_changed=3)
        base_entries = [c for c in result["co_changed"] if c["sha"] == self.info["base_sha"]]
        self.assertEqual(len(base_entries), self.info["base_total"])
        self.assertEqual(
            result["co_changed_totals"][self.info["base_sha"]], self.info["base_total"])

    def test_limits_records_the_configured_cap(self):
        result = _trace_co_changed(self.info, max_co_changed=3)
        self.assertEqual(result["limits"]["co_changed_per_commit"], 3)

    def test_default_cap_is_the_module_constant(self):
        result = tracer.trace(
            self.info["repo"], self.info["path"], self.info["line"], self.info["line"],
            include_commits=[self.info["big_sha"], self.info["base_sha"]],
        )
        self.assertEqual(result["limits"]["co_changed_per_commit"], tracer.CO_CHANGED_PER_COMMIT)


class TestCliMaxCoChangedFlag(unittest.TestCase):
    def test_max_co_changed_flag_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_co_changed_cap(tmp)
            proc = subprocess.run(
                [sys.executable, _SCRIPT, "--repo", info["repo"], "--file", info["path"],
                 "--lines", str(info["line"]), "--include-commit", info["big_sha"],
                 "--include-commit", info["base_sha"], "--max-co-changed", "3"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            import json
            result = json.loads(proc.stdout)
            self.assertEqual(result["limits"]["co_changed_per_commit"], 3)
            big_entries = [c for c in result["co_changed"] if c["sha"] == info["big_sha"]]
            self.assertEqual(len(big_entries), 3)


class TestIsTestPath(unittest.TestCase):
    def test_recognizes_test_directory_segments(self):
        for path in ("tests/foo.py", "spec/foo.rb", "__tests__/foo.js"):
            self.assertTrue(noise.is_test_path(path), path)

    def test_recognizes_camel_case_android_test_directory(self):
        self.assertTrue(noise.is_test_path("androidTest/FooBar.kt"))

    def test_recognizes_camel_case_class_name(self):
        self.assertTrue(noise.is_test_path("FooTest.kt"))

    def test_recognizes_underscore_suffixes(self):
        self.assertTrue(noise.is_test_path("foo_test.py"))
        self.assertTrue(noise.is_test_path("foo_spec.rb"))

    def test_does_not_match_test_as_a_bare_substring(self):
        # "contest" and "latest" both end in the four letters "test", in
        # all lowercase, exactly the shape a naive substring check would
        # misclassify. Neither has a capital "Test" word boundary, and
        # neither is inside a test/spec directory, so both must stay false.
        self.assertFalse(noise.is_test_path("contest.py"))
        self.assertFalse(noise.is_test_path("latest/foo.py"))


if __name__ == "__main__":
    unittest.main()
