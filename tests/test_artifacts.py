import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts

TRACE = {
    "target": {"path": "payment.py", "start": 3, "end": 3},
    "introduction_candidates": [{
        "sha": "a3f8c21" + "0" * 33, "subject": "hotfix: prevent double charge (#4127)",
        "date": "2019-11-08T02:14:00+00:00", "author": "Kim",
        "author_email": "kim@example.com", "why": "pickaxe",
    }],
    "co_changed": [{"path": "payment_test.py", "sha": "a3f8c21" + "0" * 33}],
    "blame_candidates": [], "revert_chain": [], "notes": [],
    "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago"},
}


class TestSkeleton(unittest.TestCase):
    def test_danger_skeleton_is_a_keep_comment(self):
        out = artifacts.skeleton("danger", TRACE)
        self.assertIn("KEEP", out)
        self.assertIn("a3f8c21", out)
        self.assertIn("#4127", out)

    def test_safe_skeleton_is_a_pr_body(self):
        out = artifacts.skeleton("safe", TRACE)
        self.assertIn("payment.py", out)
        self.assertIn("a3f8c21", out)

    def test_unknown_skeleton_names_who_to_ask(self):
        out = artifacts.skeleton("unknown", TRACE)
        self.assertIn("Kim", out)
        self.assertIn("kim@example.com", out)

    def test_conditional_skeleton_is_a_checklist(self):
        out = artifacts.skeleton("conditional", TRACE)
        self.assertIn("- [ ]", out)

    def test_unsupported_grade_raises(self):
        with self.assertRaises(ValueError):
            artifacts.skeleton("mostly-safe", TRACE)


class TestClipboard(unittest.TestCase):
    def test_uses_first_available_tool(self):
        with mock.patch.object(artifacts.shutil, "which",
                               side_effect=lambda t: "/usr/bin/pbcopy" if t == "pbcopy" else None):
            with mock.patch.object(artifacts.subprocess, "run") as run:
                run.return_value.returncode = 0
                tool = artifacts.to_clipboard("hello")
        self.assertEqual(tool, "pbcopy")
        run.assert_called_once()

    def test_returns_empty_string_when_no_tool_exists(self):
        with mock.patch.object(artifacts.shutil, "which", return_value=None):
            self.assertEqual(artifacts.to_clipboard("hello"), "")

    def test_returns_empty_string_when_tool_fails(self):
        with mock.patch.object(artifacts.shutil, "which",
                               side_effect=lambda t: "/usr/bin/pbcopy" if t == "pbcopy" else None):
            with mock.patch.object(artifacts.subprocess, "run") as run:
                run.return_value.returncode = 1
                tool = artifacts.to_clipboard("hello")
        self.assertEqual(tool, "")
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
