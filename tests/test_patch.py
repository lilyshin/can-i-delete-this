"""A keep-comment as a patch file the user applies themselves.

The load-bearing test in here is not that the diff looks right, it is that
`git apply` accepts it and the comment lands directly above the target
line with the target's own indentation. A patch that reads correctly and
is rejected by `git apply` is the failure this module exists to catch, so
these tests run `git apply` for real against a fixture repository.

`patch.build` itself never runs git and never writes to the target file
(see patch.py's module docstring): everything below either reads the diff
it returns or applies that diff with git in a throwaway fixture.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts
import make_fixture_repo
import patch
import trace as tracer

SCRIPTS = Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"


def _verdict(sha, *, grade="danger"):
    return {
        "grade": grade,
        "summary": "This guard prevents a double charge.",
        "evidence": [{"type": "commit", "ref": sha, "role": "introduced"}],
        "conditions": ["the duplicate guard is removed upstream"],
    }


def _apply(repo, diff):
    """Write `diff` to a file and run `git apply` on it, the way a user
    would. Returns the CompletedProcess so a test can assert on failure
    text as well as success."""
    patch_file = os.path.join(repo, "keep.patch")
    with open(patch_file, "w", encoding="utf-8") as fh:
        fh.write(diff)
    return subprocess.run(["git", "apply", "keep.patch"], cwd=repo,
                          capture_output=True, text=True)


def _read(repo, path):
    """`newline=""` because one fixture file is CRLF and universal-newline
    translation would hide exactly what that fixture is for."""
    with open(os.path.join(repo, path), encoding="utf-8", newline="") as fh:
        return fh.read()


class _FixtureCase(unittest.TestCase):
    """A fresh fixture repository per test: several of these edit the
    working tree or apply a patch to it, and a shared repo would leak
    that into the next test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_patch_targets(self.tmp.name)
        self.repo = self.info["repo"]

    def target(self, key):
        return self.info[key]

    def trace_for(self, key):
        """A real trace of one fixture target, snippet and all. Built by
        trace.py rather than by hand so these tests keep consuming the
        JSON shape trace.py actually emits."""
        t = self.target(key)
        return tracer.trace(self.repo, t["path"], t["start"], t["end"])


class TestPatchApplies(_FixtureCase):
    """`git apply` accepts the patch, and the comment lands where it was
    supposed to: directly above the target line, at the target line's own
    indentation, with nothing else in the file touched.

    The keep comment is more than one line (a KEEP line plus a guard or a
    warning line), so "directly above" means the whole block sits between
    the line before the target and the target itself.
    """

    def _apply_above_target(self, key, marker, lang="en"):
        t = self.target(key)
        before = _read(self.repo, t["path"]).split("\n")

        diff = patch.build(self.trace_for(key), _verdict(self.info["sha"]),
                           repo=self.repo, lang=lang)
        result = _apply(self.repo, diff)
        self.assertEqual(result.returncode, 0,
                         "git apply rejected the patch: " + result.stderr)

        after = _read(self.repo, t["path"]).split("\n")
        at = t["start"] - 1  # 0-based index of the target line
        inserted = len(after) - len(before)
        self.assertGreaterEqual(inserted, 1, "nothing was inserted")

        # Everything above the insertion point, and everything from the
        # target line down, is byte-identical.
        self.assertEqual(after[:at], before[:at])
        self.assertEqual(after[at + inserted:], before[at:])

        block = after[at:at + inserted]
        for line in block:
            self.assertTrue(line.startswith(t["indent"] + marker + " "),
                            "not an indented comment: " + repr(line))
        return t, block, after

    def test_python_patch_applies_and_lands_above_the_target(self):
        t, block, after = self._apply_above_target("python", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_kotlin_patch_uses_the_kotlin_marker(self):
        t, block, after = self._apply_above_target("kotlin", "//")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)], "            return")

    def test_sql_patch_uses_the_sql_marker(self):
        t, block, after = self._apply_above_target("sql", "--")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "    amount numeric(12, 2) not null,")

    def test_target_on_the_first_line_of_the_file(self):
        """No context above the insertion point at all, so the hunk starts
        at line 1 with a leading count of zero unchanged lines."""
        t, block, after = self._apply_above_target("head", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[len(block)], "import legacy_shim")

    def test_target_on_the_last_line_of_a_file_with_no_trailing_newline(self):
        t, block, after = self._apply_above_target("tail", "#")
        self.assertEqual(after[t["start"] - 1 + len(block)], "    return run(retries=3)")
        # The file had no trailing newline and must still have none.
        self.assertFalse(_read(self.repo, t["path"]).endswith("\n"))

    def test_korean_path_applies(self):
        t, block, after = self._apply_above_target("korean", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_korean_artifact_applies(self):
        t, block, after = self._apply_above_target("python", "#", lang="ko")
        self.assertIn("유지:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_crlf_file_applies_and_keeps_one_line_ending_style(self):
        """The trace's snippet lost the "\\r" to `str.splitlines()` and the
        working tree still has it, which must not read as "the target
        moved"; and the inserted comment must not leave the file with two
        line ending styles."""
        t, block, _after = self._apply_above_target("crlf", "#")
        for line in block:
            self.assertTrue(line.endswith("\r"), repr(line))
        raw = Path(os.path.join(self.repo, t["path"])).read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"),
                         "a bare LF line ending was introduced into a CRLF file")

    def test_the_whole_comment_block_is_inserted_not_just_its_first_line(self):
        info = self.trace_for("python")
        expected = artifacts.skeleton("danger", info,
                                      _verdict(self.info["sha"])["evidence"])
        t, block, _after = self._apply_above_target("python", "#")
        self.assertEqual(len(block), len(expected.split("\n")))
        self.assertEqual([line.strip() for line in block],
                         [line.strip() for line in expected.split("\n")])


class TestPatchNeverWritesTheTargetFile(_FixtureCase):
    """The whole reason this feature is allowed to exist: it produces a
    patch, it does not edit the user's code."""

    def test_build_leaves_the_target_file_untouched(self):
        t = self.target("python")
        before = _read(self.repo, t["path"])
        patch.build(self.trace_for("python"), _verdict(self.info["sha"]),
                    repo=self.repo)
        self.assertEqual(_read(self.repo, t["path"]), before)

    def test_build_leaves_the_working_tree_clean(self):
        patch.build(self.trace_for("python"), _verdict(self.info["sha"]),
                    repo=self.repo)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo,
                                capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout.strip(), "")


class TestPatchShape(_FixtureCase):
    """The diff's own text, for the parts a test above cannot see once
    git has applied it."""

    def _diff(self, key, **kwargs):
        return patch.build(self.trace_for(key), _verdict(self.info["sha"]),
                           repo=self.repo, **kwargs)

    def test_header_names_the_target_path_on_both_sides(self):
        diff = self._diff("python")
        lines = diff.splitlines()
        self.assertEqual(lines[0], "diff --git a/billing/fee.py b/billing/fee.py")
        self.assertEqual(lines[1], "--- a/billing/fee.py")
        self.assertEqual(lines[2], "+++ b/billing/fee.py")
        self.assertTrue(lines[3].startswith("@@ -"))

    def test_every_added_line_carries_the_comment_marker(self):
        info = self.trace_for("python")
        # A co-changed test on the cited commit makes skeleton() emit the
        # guard line as well as the KEEP line, so the patch has more than
        # one added line to check.
        info["co_changed"] = [{"path": "tests/test_fee.py", "sha": self.info["sha"]}]
        diff = patch.build(info, _verdict(self.info["sha"]), repo=self.repo)
        added = [l[1:] for l in diff.splitlines() if l.startswith("+")
                 and not l.startswith("+++")]
        self.assertGreater(len(added), 1)
        for line in added:
            self.assertTrue(line.startswith("        # "),
                            "added line is not an indented comment: " + repr(line))

    def test_context_lines_come_from_the_working_tree(self):
        diff = self._diff("python")
        context = [l[1:] for l in diff.splitlines()[4:] if l.startswith(" ")]
        self.assertIn("    if order.already_charged:", context)
        self.assertIn("    order.mark_processed()", context)

    def test_no_newline_at_end_of_file_is_declared(self):
        diff = self._diff("tail")
        self.assertIn("\\ No newline at end of file", diff)

    def test_no_newline_marker_is_absent_for_an_ordinary_file(self):
        self.assertNotIn("\\ No newline", self._diff("python"))

    def test_hunk_header_counts_match_the_lines_that_follow(self):
        diff = self._diff("python").splitlines()
        header = diff[3]
        body = diff[4:]
        old = len([l for l in body if l.startswith((" ", "-"))])
        new = len([l for l in body if l.startswith((" ", "+"))])
        self.assertEqual(header, "@@ -3,6 +3,8 @@")
        self.assertEqual(header.split()[1], "-3,{}".format(old))
        self.assertEqual(header.split()[2], "+3,{}".format(new))

    def test_patch_ends_with_a_newline(self):
        self.assertTrue(self._diff("python").endswith("\n"))


class TestRefusals(_FixtureCase):
    """A wrong patch is worse than no patch, so every doubt is a refusal
    with a reason a person can act on."""

    def _refuse(self, trace_data, verdict_data, **kwargs):
        with self.assertRaises(patch.Refused) as caught:
            patch.build(trace_data, verdict_data, repo=self.repo, **kwargs)
        self.assertTrue(str(caught.exception).strip(),
                        "a refusal with no reason is not a reason")
        return caught.exception

    def test_grade_safe_is_refused(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="safe"))
        self.assertEqual(refused.code, "not-danger")

    def test_grade_conditional_is_refused(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="conditional"))
        self.assertEqual(refused.code, "not-danger")

    def test_grade_unknown_is_refused(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="unknown"))
        self.assertEqual(refused.code, "not-danger")

    def test_unavailable_snippet_is_refused(self):
        info = self.trace_for("python")
        info["snippet"] = {"available": False, "reason": "missing-at-head"}
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "no-snippet")

    def test_unknown_extension_is_refused_rather_than_left_markerless(self):
        info = self.trace_for("docs")
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "no-marker")

    def test_target_beyond_the_end_of_the_file_is_refused(self):
        info = self.trace_for("python")
        info["target"]["start"] = 400
        info["target"]["end"] = 400
        info["snippet"]["target_start"] = 400
        info["snippet"]["target_end"] = 400
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "out-of-range")

    def test_edited_working_tree_is_refused(self):
        """The file moved on since the investigation, so the recorded line
        numbers may point somewhere else now."""
        t = self.target("python")
        info = self.trace_for("python")
        full = os.path.join(self.repo, t["path"])
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("# a new line at the top pushes everything down\n" + text)
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_edited_target_line_itself_is_refused(self):
        t = self.target("python")
        info = self.trace_for("python")
        full = os.path.join(self.repo, t["path"])
        with open(full, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        lines[t["start"] - 1] = "        return {'status': 'dupe'}"
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_binary_file_is_refused(self):
        info = self.trace_for("python")
        info["target"]["path"] = self.target("binary")["path"]
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "binary-file")

    def test_missing_file_is_refused(self):
        info = self.trace_for("python")
        os.remove(os.path.join(self.repo, self.target("python")["path"]))
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "missing-file")

    def test_path_outside_the_repository_is_refused(self):
        info = self.trace_for("python")
        info["target"]["path"] = "../outside.py"
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "outside-repo")

    def test_unresolved_citation_is_refused(self):
        """skeleton() answers an unresolved citation with a warning
        paragraph, not a comment. Inserting that into source would be a
        syntax error, and inserting a guessed attribution instead would be
        the misattribution this project exists to avoid."""
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict("deadbee" + "0" * 33))
        self.assertEqual(refused.code, "not-a-comment")

    def test_malformed_trace_is_refused(self):
        refused = self._refuse({"target": {}}, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "malformed-trace")

    def test_verdict_with_no_grade_is_refused_as_malformed(self):
        """A grade that is not one of verdict.py's four words is a broken
        verdict, not a grade this declines to serve, so it does not get
        quoted back inside "grade is X, not danger"."""
        info = self.trace_for("python")
        refused = self._refuse(info, {"summary": "no grade here",
                                      "evidence": []})
        self.assertEqual(refused.code, "malformed-verdict")

    def test_declined_grade_is_named_in_the_reason(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="safe"))
        self.assertIn("safe", str(refused))

    def test_refusal_reason_is_translated(self):
        info = self.trace_for("python")
        en = self._refuse(info, _verdict(self.info["sha"], grade="safe"))
        ko = self._refuse(info, _verdict(self.info["sha"], grade="safe"), lang="ko")
        self.assertEqual(en.code, ko.code)
        self.assertNotEqual(str(en), str(ko))


class TestCli(_FixtureCase):
    """The CLI is how the skill calls this, so it gets the same scrutiny
    as the function."""

    def _write_json(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return path

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "patch.py"), *args],
            capture_output=True, text=True)

    def test_prints_the_patch_to_stdout(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diff --git a/billing/fee.py", result.stdout)

    def test_out_writes_a_patch_file_that_applies(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        out = os.path.join(self.tmp.name, "keep.patch")
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        applied = subprocess.run(["git", "apply", out], cwd=self.repo,
                                 capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)

    def test_repo_defaults_to_the_one_the_trace_recorded(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        result = self._run("--trace", t, "--verdict", v)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diff --git a/billing/fee.py", result.stdout)

    def test_refusal_exits_nonzero_with_the_reason_on_stderr(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json",
                             _verdict(self.info["sha"], grade="safe"))
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("danger", result.stderr)

    def test_refusal_writes_no_out_file(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json",
                             _verdict(self.info["sha"], grade="safe"))
        out = os.path.join(self.tmp.name, "keep.patch")
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", out)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
