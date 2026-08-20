"""Regression tests for the core.quotepath escaping bug.

With git's default `core.quotepath=true`, listing changed paths for a
commit that touches a non-ASCII filename returns octal-escaped garbage
(e.g. `"\\352\\262\\260...".py`) instead of the real UTF-8 name. That
breaks trace.py's self-exclusion check (`p != path`), breaks
noise.is_test_path's `tests/` segment recognition, and would leak
the escaped garbage straight into render.py's output. These tests build a
Korean-filename fixture and pin the fixed behavior end to end.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import gitq
import noise
import trace as tracer


class TestChangedPathsIsReadable(unittest.TestCase):
    def test_korean_filename_is_not_octal_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_korean_paths(tmp)
            paths = gitq.changed_paths(info["repo"], info["real_sha"])
            self.assertIn(info["path"], paths)
            self.assertIn(info["test_path"], paths)
            # None of the returned paths should still be quoted/escaped.
            for p in paths:
                self.assertFalse(p.startswith('"'), p)
                self.assertNotIn("\\3", p, p)


class TestCoChangedExcludesTargetItself(unittest.TestCase):
    def test_target_file_is_not_in_its_own_co_changed_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_korean_paths(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
            co_changed_paths = [c["path"] for c in result["co_changed"]]
            # Only the co-changed test file should show up; the target's
            # own (escaped, pre-fix) path must not sneak in as a second,
            # spurious entry via a failed self-exclusion comparison.
            self.assertEqual(co_changed_paths, [info["test_path"]])

    def test_co_changed_paths_are_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_korean_paths(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
            co_changed_paths = [c["path"] for c in result["co_changed"]]
            self.assertIn(info["test_path"], co_changed_paths)
            for p in co_changed_paths:
                self.assertFalse(p.startswith('"'), p)


class TestIsTestPathOnKoreanSegment(unittest.TestCase):
    def test_recognizes_ascii_tests_dir_alongside_korean_filename(self):
        # No English "test"/"spec" filename marker here on purpose: this
        # must be recognized via the ASCII `tests/` directory segment
        # alone, not via a filename suffix.
        self.assertTrue(noise.is_test_path("tests/결제_확인.py"))

    def test_does_not_recognize_the_octal_escaped_form(self):
        # Sanity check on the failure mode itself: once the whole path is
        # quoted and octal-escaped, the leading quote character corrupts
        # the leading "tests" directory segment, so is_test_path can no
        # longer recognize it. This documents why the fix belongs in
        # gitq.changed_paths (stop the escaping from happening at all),
        # not in is_test_path (try to see through it after the fact).
        escaped = '"tests/\\352\\262\\260\\354\\240\\234\\353\\252\\250\\353\\223\\210.py"'
        self.assertFalse(noise.is_test_path(escaped))


if __name__ == "__main__":
    unittest.main()
