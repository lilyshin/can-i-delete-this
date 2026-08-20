"""Regression tests for final-rereview findings N1-N3.

N1: `_guard_text`/`_guard_lines`'s "and N more" tail was computed against
`co_changed`'s already-capped length, not against what trace.py's
`co_changed_totals` says the cited commit actually touched, so a capped
commit could undercount the tests it names as "N more" when the true
remainder is larger. N2: nothing in the suite pinned either number in that
tail, so a mutation that broke the arithmetic (or the "at least" wording)
would have gone unnoticed. N3: `conditional.run_guard`'s "its name ...
still passes" reads wrong when `guard` names more than one path.

These tests build the trace dict by hand rather than through a fixture
repo, so the two facts that decide the wording -- how many test-looking
paths `_tests()` sees, and whether `co_changed_totals` says the cited
commit's `co_changed` list was cut -- are set directly and unambiguously.
`tests/test_guard_capped_test_paths.py` covers the same N1 scenario
through a real fixture repo, the real tracer and a real `patch.py` run.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts

_SHA = "a3f8c21" + "0" * 33


def _trace(shown, total, *, lang_paths=None):
    """A trace whose cited (and only) candidate co-changed `shown`
    test-looking paths, out of `total` the commit is said to have really
    touched (`co_changed_totals[_SHA] = total`). `shown == total` means
    the cited sha was never capped; `shown < total` means it was.
    """
    paths = lang_paths or ["t/case_{:02d}_test.py".format(i) for i in range(1, shown + 1)]
    return {
        "target": {"path": "app/service.py", "start": 3, "end": 3},
        "introduction_candidates": [{
            "sha": _SHA, "subject": "hotfix: prevent double charge (#4127)",
            "date": "2026-08-20T09:00:00+00:00", "author": "Ryan",
            "author_email": "ryan@example.com", "why": "pickaxe",
        }],
        "co_changed": [{"path": p, "sha": _SHA} for p in paths],
        "co_changed_totals": {_SHA: total},
        "blame_candidates": [], "revert_chain": [], "notes": [],
        "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago"},
    }


class TestUncappedRemainderIsExact(unittest.TestCase):
    """The cited sha's co_changed_totals entry equals what is present, so
    the tool has actually seen every test-looking path this commit
    touched: the remainder it reports can be an exact count."""

    def test_four_uncapped_pins_and_one_more(self):
        out = artifacts.skeleton("danger", _trace(4, 4))
        self.assertIn("#   and 1 more", out.splitlines())
        self.assertNotIn("and at least 1 more", out)

    def test_twelve_uncapped_pins_and_nine_more_en(self):
        out = artifacts.skeleton("danger", _trace(12, 12))
        self.assertIn("#   and 9 more", out.splitlines())
        self.assertNotIn("and at least 9 more", out)

    def test_twelve_uncapped_pins_and_nine_more_ko(self):
        out = artifacts.skeleton("danger", _trace(12, 12), lang="ko")
        self.assertIn("#   외 9개 더", out.splitlines())
        self.assertNotIn("외 최소 9개 더", out)

    def test_named_paths_are_one_per_line(self):
        out = artifacts.skeleton("danger", _trace(4, 4))
        lines = out.splitlines()
        self.assertIn("#   t/case_01_test.py", lines)
        self.assertIn("#   t/case_02_test.py", lines)
        self.assertIn("#   t/case_03_test.py", lines)
        # The fourth path is not shown by name: only the first
        # _MAX_NAMED_GUARDS survive as their own line, the rest are the
        # "and 1 more" count.
        self.assertNotIn("case_04_test.py", out)

    def test_intro_line_is_plural_and_marker_prefixed(self):
        out = artifacts.skeleton("danger", _trace(4, 4))
        self.assertIn(
            "# Before deleting, confirm these still pass (names look "
            "like tests, not confirmed):",
            out.splitlines(),
        )

    def test_closing_line_unchanged(self):
        out = artifacts.skeleton("danger", _trace(4, 4))
        self.assertIn(
            "# If none of these are tests, no test guards this: add one "
            "before touching it.",
            out.splitlines(),
        )


class TestCappedRemainderSaysAtLeast(unittest.TestCase):
    """5 of 30 test-looking paths survived trace.py's per-commit cap
    (this is the exact N1 reproduction: 5 shown, 25 more the cap cut
    before _tests() ever saw them). The tool cannot know the true
    remainder among the named-but-unshown paths, only that at least this
    many exist, so the wording must say so."""

    def test_capped_pins_and_at_least_two_more_en(self):
        out = artifacts.skeleton("danger", _trace(5, 30))
        self.assertIn("#   and at least 2 more", out.splitlines())
        self.assertNotIn("and 2 more", out)

    def test_capped_pins_and_at_least_two_more_ko(self):
        out = artifacts.skeleton("danger", _trace(5, 30), lang="ko")
        self.assertIn("#   외 최소 2개 더", out.splitlines())
        self.assertNotIn("외 2개 더", out)

    def test_unknown_total_is_treated_as_capped(self):
        # An older trace with no co_changed_totals key at all cannot say
        # whether the cited sha was capped, so it must not claim an exact
        # remainder it cannot support (see _co_changed_capped).
        trace = _trace(5, 5)
        del trace["co_changed_totals"]
        out = artifacts.skeleton("danger", trace)
        self.assertIn("#   and at least 2 more", out.splitlines())


class TestConditionalRunGuardPlural(unittest.TestCase):
    """N3: the checklist's `conditional.run_guard` line was written for a
    single guard ("its name ... it actually covers this") and read wrong
    once `guard` names more than one path."""

    def test_single_guard_keeps_the_singular_wording(self):
        out = artifacts.skeleton("conditional", _trace(1, 1))
        self.assertIn(
            "- [ ] Run t/case_01_test.py (its name looks like a test, "
            "not confirmed; check it actually covers this)",
            out.splitlines(),
        )

    def test_multiple_guards_use_plural_wording(self):
        out = artifacts.skeleton("conditional", _trace(4, 4))
        lines = out.splitlines()
        matching = [l for l in lines if l.startswith("- [ ] Run ")]
        self.assertEqual(len(matching), 1)
        self.assertIn("these names look like tests, not confirmed", matching[0])
        self.assertIn("check they actually cover this", matching[0])
        self.assertNotIn("its name looks like a test", matching[0])

    def test_multiple_guards_stay_one_comma_joined_checklist_line(self):
        # Unlike the danger branch, the checklist keeps the comma-joined
        # single-line form -- it is not inserted into source through
        # patch.py, so the line-length pressure that split the danger
        # branch does not apply here.
        out = artifacts.skeleton("conditional", _trace(4, 4))
        matching = [l for l in out.splitlines() if l.startswith("- [ ] Run ")]
        self.assertIn("t/case_01_test.py, t/case_02_test.py, "
                      "t/case_03_test.py, and 1 more", matching[0])


if __name__ == "__main__":
    unittest.main()
