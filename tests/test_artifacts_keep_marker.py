"""The KEEP comment (and its guard/warning lines) must use the target
file's own comment marker, not a hardcoded `//`. A block-comment "// KEEP:"
pasted above a Python, Elixir, shell or SQL target is a syntax error, not
a comment -- see scanner.COMMENT_MARKERS for the marker table this pulls
from and artifacts.py's module docstring for why the marker itself is not
chrome (it is the target file's own syntax) while the words around it are.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts

SHA = "a3f8c21" + "0" * 33
SUBJECT = "hotfix: prevent double charge (#4127)"


def _trace(path, *, co_changed=None):
    """A minimal danger-shaped trace whose only varying is the target path,
    so each test isolates the marker lookup and nothing else."""
    return {
        "target": {"path": path, "start": 3, "end": 3},
        "introduction_candidates": [{
            "sha": SHA, "subject": SUBJECT,
            "date": "2019-11-08T02:14:00+00:00", "author": "Kim",
            "author_email": "kim@example.com", "why": "pickaxe",
        }],
        "co_changed": co_changed or [],
        "blame_candidates": [], "revert_chain": [], "notes": [],
        "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago"},
    }


def _guarded_trace(path):
    """Same as _trace, but with a co-changed test on the cited commit, so
    the danger.guard line is emitted instead of danger.warning."""
    return _trace(path, co_changed=[{"path": "billing/fee_test.py", "sha": SHA}])


class TestKeepMarkerByExtension(unittest.TestCase):
    """`.py` target -> `# KEEP:`"""

    def test_py_target_uses_hash_marker(self):
        out = artifacts.skeleton("danger", _trace("billing/fee.py"))
        self.assertIn("# KEEP:", out)
        self.assertNotIn("// KEEP", out)

    def test_ex_target_uses_hash_marker(self):
        out = artifacts.skeleton("danger", _trace("lib/billing/fee.ex"))
        self.assertIn("# KEEP:", out)
        self.assertNotIn("// KEEP", out)

    def test_kt_target_uses_slash_slash_marker(self):
        out = artifacts.skeleton("danger", _trace("Fee.kt"))
        self.assertIn("// KEEP:", out)

    def test_sql_target_uses_dash_dash_marker(self):
        out = artifacts.skeleton("danger", _trace("migrations/0001_fee.sql"))
        self.assertIn("-- KEEP:", out)
        self.assertNotIn("// KEEP", out)


class TestKeepMarkerUnknownExtension(unittest.TestCase):
    """An extension absent from scanner.COMMENT_MARKERS (`.rst`) or a path
    with no extension at all (`Makefile`) must not guess a marker: the
    KEEP text comes out bare, plus one sentence telling the reader to add
    their own language's marker."""

    def test_rst_target_has_no_marker_and_explains(self):
        out = artifacts.skeleton("danger", _trace("docs/fee.rst"))
        self.assertNotIn("//", out)
        self.assertNotIn("# KEEP", out)
        self.assertNotIn("-- KEEP", out)
        lines = out.splitlines()
        keep_line = next(l for l in lines if "KEEP:" in l)
        self.assertTrue(keep_line.startswith("KEEP:"))
        self.assertTrue(any("comment marker" in l for l in lines))

    def test_makefile_target_has_no_marker_and_explains(self):
        out = artifacts.skeleton("danger", _trace("Makefile"))
        self.assertNotIn("//", out)
        lines = out.splitlines()
        keep_line = next(l for l in lines if "KEEP:" in l)
        self.assertTrue(keep_line.startswith("KEEP:"))
        self.assertTrue(any("comment marker" in l for l in lines))


class TestKeepMarkerOnGuardAndWarningLines(unittest.TestCase):
    """A fix that only touches the KEEP line and leaves danger.guard or
    danger.warning on a stale `//` is exactly the bug this task removes."""

    def test_warning_line_uses_target_marker(self):
        out = artifacts.skeleton("danger", _trace("billing/fee.py"))
        self.assertIn("# WARNING", out)
        self.assertNotIn("// WARNING", out)

    def test_guard_line_uses_target_marker(self):
        out = artifacts.skeleton("danger", _guarded_trace("billing/fee.py"))
        self.assertIn("# Before deleting", out)
        self.assertNotIn("// Before deleting", out)

    def test_sql_guard_line_uses_dash_dash(self):
        out = artifacts.skeleton("danger", _guarded_trace("migrations/0001_fee.sql"))
        self.assertIn("-- Before deleting", out)
        self.assertNotIn("// Before deleting", out)


class TestKeepMarkerIsLanguageIndependent(unittest.TestCase):
    """The comment marker is the target file's syntax, not chrome: it must
    be identical in en and ko output for the same path, even though the
    words around it are translated."""

    def test_ko_py_target_uses_hash_marker(self):
        out = artifacts.skeleton("danger", _trace("billing/fee.py"), lang="ko")
        self.assertIn("# 유지:", out)
        self.assertNotIn("// 유지", out)

    def test_ko_sql_target_uses_dash_dash_marker(self):
        out = artifacts.skeleton("danger", _trace("migrations/0001_fee.sql"), lang="ko")
        self.assertIn("-- 유지:", out)

    def test_en_and_ko_agree_on_marker_for_same_path(self):
        en = artifacts.skeleton("danger", _trace("billing/fee.py"), lang="en")
        ko = artifacts.skeleton("danger", _trace("billing/fee.py"), lang="ko")
        self.assertIn("#", en.splitlines()[0])
        self.assertIn("#", ko.splitlines()[0])

    def test_ko_rst_target_has_no_marker_and_explains(self):
        out = artifacts.skeleton("danger", _trace("docs/fee.rst"), lang="ko")
        self.assertNotIn("//", out)
        lines = out.splitlines()
        keep_line = next(l for l in lines if "유지:" in l)
        self.assertTrue(keep_line.startswith("유지:"))
        self.assertTrue(any("주석 기호" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
