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


EMPTY_TRACE = {
    "target": {"path": "legacy.py", "start": 10, "end": 12},
    "introduction_candidates": [],
    "co_changed": [],
    "blame_candidates": [], "revert_chain": [], "notes": [],
    "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago",
               "candidate_cap_reached": False},
}


class TestEmptyTrace(unittest.TestCase):
    """F4-style trace: introduction_candidates came up empty. Nothing should
    leak the literal word "None" or leave a dangling ", " where a date or
    subject was supposed to be."""

    def test_no_grade_leaks_none_or_breaks_punctuation(self):
        for grade in ("danger", "conditional", "safe", "unknown"):
            with self.subTest(grade=grade):
                out = artifacts.skeleton(grade, EMPTY_TRACE)
                self.assertNotIn("None", out)
                self.assertNotIn("(, ", out)

    def test_danger_and_unknown_report_date_unknown_with_no_candidates(self):
        for grade in ("danger", "unknown"):
            with self.subTest(grade=grade):
                out = artifacts.skeleton(grade, EMPTY_TRACE)
                self.assertIn("date unknown", out)

    def test_danger_skeleton_warns_with_no_candidates(self):
        out = artifacts.skeleton("danger", EMPTY_TRACE)
        self.assertIn("KEEP", out)
        self.assertIn("unknown", out)
        self.assertIn("no test guards this", out)

    def test_explicit_none_date_does_not_leak(self):
        trace_with_none_date = {
            **TRACE,
            "introduction_candidates": [{
                **TRACE["introduction_candidates"][0],
                "date": None,
            }],
        }
        out = artifacts.skeleton("danger", trace_with_none_date)
        self.assertNotIn("None", out)
        self.assertIn("date unknown", out)

    def test_explicit_none_sha_does_not_leak(self):
        trace_with_none_sha = {
            **TRACE,
            "introduction_candidates": [{
                **TRACE["introduction_candidates"][0],
                "sha": None,
            }],
        }
        out = artifacts.skeleton("danger", trace_with_none_sha)
        self.assertNotIn("None", out)
        self.assertIn("unknown", out)

    def test_unknown_skeleton_includes_notes_and_limits(self):
        trace_with_notes = {
            **EMPTY_TRACE,
            "notes": ["blame returned only noise commits; falling back to pickaxe"],
            "limits": {"truncated": True, "max_commits": 5000, "since": "5 years ago",
                       "candidate_cap_reached": True},
        }
        out = artifacts.skeleton("unknown", trace_with_notes)
        self.assertIn("Investigation notes", out)
        self.assertIn("blame returned only noise commits; falling back to pickaxe", out)
        self.assertIn("history search was truncated", out)
        self.assertIn("candidate cap was reached", out)

    def test_unknown_skeleton_omits_notes_section_when_notes_empty(self):
        out = artifacts.skeleton("unknown", EMPTY_TRACE)
        self.assertNotIn("Investigation notes", out)
        self.assertNotIn("Search was limited", out)


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
