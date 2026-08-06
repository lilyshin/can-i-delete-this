"""trace.py's CLI must give a human a clean, non-zero-exit error message for
common bad input (a path that does not exist, a line range past the end of
the file, a malformed --lines value), instead of a raw Python traceback.
Genuinely unexpected errors (anything not one of these three shapes) must
still surface in full, not be swallowed.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixture_repo

_SCRIPT = str(
    Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts" / "trace.py"
)


def _run(*args):
    return subprocess.run(
        [sys.executable, _SCRIPT, *args],
        capture_output=True, text=True,
    )


class TestCleanCliErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f1(self.tmp.name)

    def test_nonexistent_file_is_a_clean_error(self):
        proc = _run("--repo", self.info["repo"], "--file", "nope.py", "--lines", "1:1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("nope.py", proc.stderr)

    def test_out_of_range_lines_is_a_clean_error(self):
        proc = _run("--repo", self.info["repo"], "--file", "payment.py", "--lines", "100:105")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)

    def test_malformed_lines_is_a_clean_error(self):
        proc = _run("--repo", self.info["repo"], "--file", "payment.py", "--lines", "four")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("--lines", proc.stderr)

    def test_valid_input_still_prints_json_and_exits_zero(self):
        proc = _run("--repo", self.info["repo"], "--file", "payment.py", "--lines", "3:3")
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"target"', proc.stdout)


if __name__ == "__main__":
    unittest.main()
