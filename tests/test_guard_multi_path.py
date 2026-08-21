"""Regression tests for final-rereview findings N1-N3, and for the boundary
the second re-review round found in the N1 fix itself.

N1: `_guard_text`/`_guard_lines`'s "and N more" tail was computed against
`co_changed`'s already-capped length, not against what trace.py's
`co_changed_totals` says the cited commit actually touched, so a capped
commit could undercount the tests it names as "N more" when the true
remainder is larger. N2: nothing in the suite pinned either number in that
tail, so a mutation that broke the arithmetic (or the "at least" wording)
would have gone unnoticed. N3: `conditional.run_guard`'s "its name ...
still passes" reads wrong when `guard` names more than one path.

The N1 fix's own boundary: when the surviving test-looking path count is
already `<= _MAX_NAMED_GUARDS`, `extra` is 0 and the "and N more"/"and at
least N more" tail never fires at all, even when the cited commit's
`co_changed` list was capped -- so a commit that touched far more files
than are shown said nothing about it. `TestListCappedQuadrants` pins all
four combinations of {capped, uncapped} x {extra == 0, extra > 0}: only
the first is new behavior, the other three must render exactly as
before.

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
import scanner

_SHA = "a3f8c21" + "0" * 33


def _trace(shown, total, *, override_paths=None):
    """A trace whose cited (and only) candidate co-changed `shown`
    test-looking paths, out of `total` the commit is said to have really
    touched (`co_changed_totals[_SHA] = total`). `shown == total` means
    the cited sha was never capped; `shown < total` means it was.

    `override_paths` replaces the generated `t/case_NN_test.py` names
    with the caller's own list (see `TestGuardLineLengthDiscipline`,
    which passes real long paths through here); it has nothing to do
    with language, unlike its old name suggested.
    """
    paths = override_paths or ["t/case_{:02d}_test.py".format(i) for i in range(1, shown + 1)]
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
            "# Before deleting, confirm these pass (tests by name, "
            "not confirmed):",
            out.splitlines(),
        )

    def test_closing_line_unchanged(self):
        out = artifacts.skeleton("danger", _trace(4, 4))
        self.assertIn(
            "# If none are tests, no test guards this: add one "
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


class TestListCappedQuadrants(unittest.TestCase):
    """The N1 fix's own gap: `extra == 0` and `capped` True produced no
    disclosure line at all, because the "and N more" tail only ever fires
    when `extra > 0`. All four combinations pinned here; only the first
    is new -- the other three must be exactly what they were before this
    class existed.
    """

    def _tail(self, out):
        lines = out.splitlines()
        return [l for l in lines
                if l.startswith("#   and") or l.startswith("#   외")
                or l.startswith("#   더")]

    def test_capped_with_extra_zero_discloses_the_list_cut_en(self):
        # 3 test-looking paths present (all _MAX_NAMED_GUARDS fit, so
        # extra is 0), but co_changed_totals says the commit really
        # touched 12 -- the cap cut 9 files before _tests() ever saw
        # them. Those 9 are not known to be tests, so the line must not
        # claim a test count, only that the list itself was cut.
        out = artifacts.skeleton("danger", _trace(3, 12))
        self.assertEqual(
            self._tail(out),
            ["#   and possibly more: 3 of 12 files from this commit are listed"],
        )

    def test_capped_with_extra_zero_discloses_the_list_cut_ko(self):
        out = artifacts.skeleton("danger", _trace(3, 12), lang="ko")
        self.assertEqual(
            self._tail(out),
            ["#   더 있을 수 있음: 이 커밋이 건드린 파일 12개 중 3개만 나열됨"],
        )

    def test_capped_with_extra_above_zero_is_unchanged(self):
        # Already covered by TestCappedRemainderSaysAtLeast; repeated here
        # so all four quadrants are visible side by side in one place.
        out = artifacts.skeleton("danger", _trace(5, 30))
        self.assertEqual(self._tail(out), ["#   and at least 2 more"])

    def test_uncapped_with_extra_zero_stays_silent(self):
        # A complete list -- co_changed_totals agrees with what is
        # present, and every test-looking path fits without a count --
        # must not gain a disclosure line just because this class exists.
        # Saying something here would be the mirror-image bug: labelling
        # a complete list as partial.
        out = artifacts.skeleton("danger", _trace(2, 2))
        self.assertEqual(self._tail(out), [])
        self.assertNotIn("possibly more", out)
        self.assertNotIn("나열됨", out)

    def test_uncapped_with_extra_above_zero_is_unchanged(self):
        # Already covered by TestUncappedRemainderIsExact, repeated here
        # for the same side-by-side reason as above.
        out = artifacts.skeleton("danger", _trace(4, 4))
        self.assertEqual(self._tail(out), ["#   and 1 more"])

    def test_unknown_total_with_extra_zero_has_no_numbers_to_disclose(self):
        # An old-format trace with no co_changed_totals key cannot say how
        # many files the commit really touched, so the disclosure line
        # cannot claim specific numbers either -- it has to say that the
        # count itself is unknown, not fabricate a total.
        trace = _trace(3, 3)
        del trace["co_changed_totals"]
        out = artifacts.skeleton("danger", trace)
        self.assertEqual(
            self._tail(out),
            ["#   and possibly more: this trace does not record the "
             "total files touched"],
        )


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


class TestSingleGuardIsAlsoLineSplit(unittest.TestCase):
    """0.9.2 kept exactly one guard on a single combined sentence
    ("...confirm X (its name...) still passes.") and only switched to one
    path per line once a second path showed up. A single real path plus
    the wording around it was already enough on its own -- 154 chars once
    patch.py's own indentation was added on top -- to blow past a
    linter's max line length, so the split must apply unconditionally,
    not just above some count this module has no way to threshold on
    (see TestGuardLineLengthDiscipline below for why no such threshold
    exists here).
    """

    def test_intro_path_and_closing_are_three_separate_lines_en(self):
        out = artifacts.skeleton("danger", _trace(1, 1))
        lines = out.splitlines()
        intro = [l for l in lines if l.startswith("# Before deleting")]
        self.assertEqual(len(intro), 1)
        self.assertNotIn("t/case_01_test.py", intro[0])
        self.assertIn("#   t/case_01_test.py", lines)

    def test_intro_path_and_closing_are_three_separate_lines_ko(self):
        out = artifacts.skeleton("danger", _trace(1, 1), lang="ko")
        lines = out.splitlines()
        intro = [l for l in lines if l.startswith("# 삭제하기 전에")]
        self.assertEqual(len(intro), 1)
        self.assertNotIn("t/case_01_test.py", intro[0])
        self.assertIn("#   t/case_01_test.py", lines)

    def test_intro_line_is_singular_not_plural_wording_en(self):
        # I2: forcing intro_key to the plural key unconditionally passed
        # every test in this suite until this pin existed, because the
        # two intro/path/closing tests above only check the shared prefix
        # ("# Before deleting"), which both the singular and plural
        # sentences start with. Pinned verbatim, the same way
        # TestUncappedRemainderIsExact::test_intro_line_is_plural_and_marker_prefixed
        # pins the plural sentence.
        out = artifacts.skeleton("danger", _trace(1, 1))
        self.assertIn(
            "# Before deleting, confirm this passes (a test by name, "
            "not confirmed):",
            out.splitlines(),
        )
        self.assertNotIn("confirm these pass", out)

    def test_intro_line_is_singular_not_plural_wording_ko(self):
        out = artifacts.skeleton("danger", _trace(1, 1), lang="ko")
        self.assertIn(
            "# 삭제하기 전에 아래 파일이 통과하는지 확인하세요"
            "(이름상 테스트로 보이나 확인되지 않음):",
            out.splitlines(),
        )
        self.assertNotIn("파일들이 모두 통과하는지", out)

    def test_single_guard_keeps_the_singular_closing_wording(self):
        out = artifacts.skeleton("danger", _trace(1, 1))
        self.assertIn(
            "# If it is not a test, no test guards this: add one before "
            "touching it.",
            out.splitlines(),
        )
        self.assertNotIn("If none are tests", out)

    def test_single_capped_guard_still_discloses_the_list_cut(self):
        # One test-looking path survived a cap that cut the rest of this
        # commit's co_changed list before _tests() ever saw them: the one
        # named path is not the whole story, so this must still carry a
        # disclosure line, the same as the multi-path capped case does.
        out = artifacts.skeleton("danger", _trace(1, 4))
        self.assertIn(
            "#   and possibly more: 1 of 4 files from this commit are listed",
            out.splitlines(),
        )


class TestTwoAndThreePathsRemainOnePerLine(unittest.TestCase):
    """The task's four named checkpoints (2, 3, 4, 12 paths) are otherwise
    covered piecemeal by TestUncappedRemainderIsExact (4, 12) and
    TestCappedRemainderSaysAtLeast (5 of 30); 2 and 3 are pinned here so
    every checkpoint has direct coverage in one place, and so a mutation
    that only breaks the 2-or-3-path boundary (as opposed to 1 or 4+)
    would be caught.
    """

    def test_two_paths_are_named_one_per_line_with_no_tail(self):
        out = artifacts.skeleton("danger", _trace(2, 2))
        lines = out.splitlines()
        self.assertIn("#   t/case_01_test.py", lines)
        self.assertIn("#   t/case_02_test.py", lines)
        self.assertFalse(any(l.startswith("#   and") for l in lines))

    def test_three_paths_are_named_one_per_line_with_no_tail(self):
        out = artifacts.skeleton("danger", _trace(3, 3))
        lines = out.splitlines()
        for i in (1, 2, 3):
            self.assertIn("#   t/case_{:02d}_test.py".format(i), lines)
        self.assertFalse(any(l.startswith("#   and") for l in lines))


class TestGuardLineLengthDiscipline(unittest.TestCase):
    """No max-line-length constant exists in artifacts.py to branch on
    here: this module knows the comment marker it is about to prefix each
    line with, but not the indentation `patch.py` adds once the line
    reaches the target file, so any threshold it picked would be a guess
    about a length it never gets to see. Splitting the output so no line
    ever carries more than one path, with a short fixed sentence around
    that path, keeps every line short by construction instead of by a
    guessed limit -- checked here by subtracting each real path back out
    of the rendered lines and confirming what remains stays under I3's
    75-character prose budget (see `TestKeepCommentProseLineLength` below
    for the budget itself, checked directly against `_STRINGS`), for both
    a single long path and a dozen of them.
    """

    _LONG_PATH = "apps/bombay/lib/bombay/schemas/space_settings_configuration_test.exs"

    def test_single_long_path_keeps_non_path_text_short(self):
        trace = _trace(1, 1, override_paths=[self._LONG_PATH])
        out = artifacts.skeleton("danger", trace)
        for line in out.splitlines():
            without_path = line.replace(self._LONG_PATH, "")
            self.assertLessEqual(len(without_path), 75, repr(line))

    def test_twelve_long_paths_keep_non_path_text_short(self):
        long_paths = [
            "apps/bombay/lib/bombay/schemas/space_settings_configuration_{:02d}_test.exs".format(i)
            for i in range(1, 13)
        ]
        trace = _trace(12, 12, override_paths=long_paths)
        out = artifacts.skeleton("danger", trace)
        for line in out.splitlines():
            stripped = line
            for p in long_paths:
                stripped = stripped.replace(p, "")
            self.assertLessEqual(len(stripped), 75, repr(line))


class TestGuardBlockLineOrder(unittest.TestCase):
    """I3: nothing in the suite pinned the guard block's line *order*,
    only that each line existed somewhere in the output. Emitting the
    path lines above the intro line still passes every marker-prefix and
    presence check these tests otherwise run, and produces a well-formed
    marker-prefixed comment that `patch.py` will happily nail into the
    user's source file -- with the intro's "confirm this passes:" colon
    pointing at nothing above it, and the path floating under the
    KEEP line instead of under its own intro. That is exactly the durable,
    unreadable-in-review defect class this project ranks worst, so order
    is checked here with index comparisons on the split lines, not
    substring presence, for both the single-path case (pinned as an exact
    sequence) and a capped multi-path case whose tail line's position also
    needs pinning.
    """

    def test_single_path_block_is_exactly_keep_intro_path_closing_in_order(self):
        out = artifacts.skeleton("danger", _trace(1, 1))
        self.assertEqual(out.splitlines(), [
            "# KEEP: hotfix: prevent double charge (#4127) (2026-08-20, a3f8c21)",
            "# Before deleting, confirm this passes (a test by name, "
            "not confirmed):",
            "#   t/case_01_test.py",
            "# If it is not a test, no test guards this: add one before "
            "touching it.",
        ])

    def test_multi_path_keeps_intro_before_paths_before_tail_before_closing(self):
        # _trace(5, 30): 5 test-looking paths present, 3 named
        # (_MAX_NAMED_GUARDS), a capped "and at least 2 more" tail line,
        # then the closing line -- four line kinds in one block, so the
        # order among all four is pinned at once.
        out = artifacts.skeleton("danger", _trace(5, 30))
        lines = out.splitlines()
        intro_idx = lines.index(
            "# Before deleting, confirm these pass (tests by name, "
            "not confirmed):"
        )
        path_idxs = [lines.index("#   t/case_{:02d}_test.py".format(i))
                     for i in (1, 2, 3)]
        tail_idx = lines.index("#   and at least 2 more")
        closing_idx = lines.index(
            "# If none are tests, no test guards this: add one "
            "before touching it."
        )
        self.assertLess(intro_idx, min(path_idxs))
        self.assertLess(max(path_idxs), tail_idx)
        self.assertLess(tail_idx, closing_idx)


# I3: which of `_STRINGS`' entries can end up as a line in a `danger`
# skeleton's KEEP comment, and how that line is prefixed once it does.
# `danger.no_marker` is deliberately absent: it is only ever appended when
# `marker` is None, and `patch.py` already refuses a markerless file
# before it would ever insert anything, so that line never reaches source
# regardless of its own length. Every entry here does reach source, and
# each is exercised with every data placeholder blanked to "" -- the same
# stance this project takes on a path (a fact is never shortened to fit),
# generalized to every other fact these lines can carry (a sha, a day, a
# subject, a count): only the chrome this module itself writes is bounded
# here.
_DANGER_KEEP_LINE_ENTRIES = [
    ("danger.keep", "marker", {"subject": "", "day": "", "sha": ""}),
    ("danger.guard_intro", "marker", {}),
    ("danger.guard_plural_intro", "marker", {}),
    ("danger.guard_unverified", "marker", {}),
    ("danger.guard_unverified_plural", "marker", {}),
    ("danger.warning", "marker", {}),
    ("guard.and_more", "guard", {"count": ""}),
    ("guard.and_at_least_more", "guard", {"count": ""}),
    ("guard.list_capped", "guard", {"listed": "", "total": ""}),
    ("guard.list_capped_unknown", "guard", {}),
]

# Keys this test suite deliberately does not cover, and why. Kept as its
# own constant, rather than inline in the coverage test, so that adding a
# new exclusion is a one-line, visible decision instead of a silent edit
# to the assertion itself.
_DANGER_KEEP_EXCLUDED_KEYS = frozenset({
    # Only ever appended when `marker` is None, and `patch.py` already
    # refuses a markerless file before it would insert anything, so this
    # line never reaches source regardless of its own length.
    "danger.no_marker",
})

# The longest comment marker `scanner.COMMENT_MARKERS` knows about ("//",
# "--"), used in place of a real one so this test bounds the worst case,
# not just whichever marker a particular fixture happens to use.
_WORST_MARKER = "x" * max(len(m) for m in scanner.COMMENT_MARKERS.values())
_WORST_MARKER_PREFIX = _WORST_MARKER + " "
_WORST_GUARD_PREFIX = _WORST_MARKER_PREFIX + "  "


class TestKeepCommentProseLineLength(unittest.TestCase):
    """I3: `docs/stability.md` used to blame an over-length KEEP comment
    line on long repository paths alone. A real end-to-end run
    (`tests/test_guard_capped_test_paths.py`) found the actual longest
    line was this module's own prose, with a short path sitting right
    next to it under the line limit. Fixing the doc's claim meant making
    it true: every string this module can write into a danger skeleton's
    KEEP comment is now kept to 75 characters or fewer once its own
    prefix (comment marker, and for a guard sub-line, its extra two-space
    indent) is included -- 75 so that even a 4-space file indent on top
    of it stays under a linter's typical 79-column default.

    Data-driven over `_STRINGS` itself, via `_DANGER_KEEP_LINE_ENTRIES`,
    not a list of literal rendered lines. `_DANGER_KEEP_LINE_ENTRIES` is
    itself a hand-written literal, though, so this test alone would not
    notice a new key added to `_STRINGS` without also being added here;
    `TestDangerKeepLineEntriesCoverTheStringTable` below is what makes
    that omission fail loudly instead of silently passing.
    """

    def test_every_entry_stays_within_the_prose_budget(self):
        for lang in ("en", "ko"):
            for key, prefix_kind, data_kwargs in _DANGER_KEEP_LINE_ENTRIES:
                with self.subTest(lang=lang, key=key):
                    if prefix_kind == "marker":
                        rendered = artifacts._t(
                            lang, key, marker=_WORST_MARKER_PREFIX, **data_kwargs)
                    else:
                        rendered = _WORST_GUARD_PREFIX + artifacts._t(
                            lang, key, **data_kwargs)
                    self.assertLessEqual(len(rendered), 75, repr(rendered))

    def test_the_longest_entry_matches_stability_md(self):
        # N1: docs/stability.md's Known-limitations entry states a
        # concrete number ("the longest it actually reaches ... is 74")
        # rather than just the 75-character cap, because a real
        # end-to-end run needs a real figure to add the target's own
        # indentation to. That number is a claim about this table's
        # actual content, not just its bound, so it has to be pinned
        # here or it goes stale exactly the way the doc's line-length
        # entry has gone stale twice before.
        longest = 0
        for lang in ("en", "ko"):
            for key, prefix_kind, data_kwargs in _DANGER_KEEP_LINE_ENTRIES:
                if prefix_kind == "marker":
                    rendered = artifacts._t(
                        lang, key, marker=_WORST_MARKER_PREFIX, **data_kwargs)
                else:
                    rendered = _WORST_GUARD_PREFIX + artifacts._t(
                        lang, key, **data_kwargs)
                longest = max(longest, len(rendered))
        self.assertEqual(longest, 74)


class TestDangerKeepLineEntriesCoverTheStringTable(unittest.TestCase):
    """N5: the previous round's docstring claimed a future key added to
    `_STRINGS` without a length check "is caught the same way" the three
    over-budget keys the review measured were -- but `_DANGER_KEEP_LINE_ENTRIES`
    had nothing tying it to `_STRINGS` itself. The re-review's mutation
    (a new 180-character `danger.mutated_extra` key, wired into the
    danger branch) left `TestKeepCommentProseLineLength` green; only
    unrelated exact-sequence pins caught it. This test is what makes that
    claim true: every `danger.*`/`guard.*` key in `_STRINGS["en"]`,
    except the ones `_DANGER_KEEP_EXCLUDED_KEYS` names and explains, must
    be one of `_DANGER_KEEP_LINE_ENTRIES`'s own keys -- in both
    directions, so a stale exclusion or a stale entry for a key that no
    longer exists is caught too, not only a missing one.
    """

    def test_every_danger_and_guard_key_is_covered(self):
        prefixed = {k for k in artifacts._STRINGS["en"]
                    if k.startswith("danger.") or k.startswith("guard.")}
        covered = {key for key, _, _ in _DANGER_KEEP_LINE_ENTRIES}
        self.assertEqual(
            prefixed - _DANGER_KEEP_EXCLUDED_KEYS, covered,
            "a danger./guard. key is not covered by "
            "_DANGER_KEEP_LINE_ENTRIES (or an excluded key no longer "
            "needs excluding, or a covered key no longer exists)")


if __name__ == "__main__":
    unittest.main()
