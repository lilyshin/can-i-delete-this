"""Regression test for the second 0.9.2 field finding: calling
`artifacts.skeleton()` with no `evidence` against a real trace that had 7
`introduction_candidates` produced a confident KEEP comment citing the
first candidate -- a 2020 commit unrelated to the target. `_top`'s
"fallback" branch cannot tell candidates apart without a citation, and
before this fix it picked the chronologically oldest one anyway whenever
`introduction_candidates` was non-empty, for any count at all.

Neither production call site (`patch.py`, and `artifacts.py`'s own CLI)
validates the verdict before reaching `skeleton()`: `patch.py` checks only
`grade`, and `artifacts.py`'s CLI checks nothing at all. So this gap is
live through both of them whenever the verdict they are handed never went
through `verdict.validate`, not only when a caller invokes `skeleton()`
directly -- the shipped CLI reproduces it with a two-file, one-command
input (a verdict with a `grade` and no `evidence` at all). That is exactly
what happened during the 0.9.2 field run this test reproduces.

`_ambiguous_citation_text` is a distinct sentence pair from
`_unresolved_citation_text`'s, not a reuse of it (see task-1-review's I1):
reusing the unresolved-citation wording asserted a citation had been made
and failed to resolve ("the verdict cites commit unknown as evidence"),
which was false when no citation was made at all -- the missing-sha
placeholder leaked straight into prose, in both languages. The fix names
only the candidate *count* (a plain git fact that explains why nothing
could be named) and never the candidates themselves, since listing shas
would invite picking the first one, the original bug wearing a different
hat.
`tests/test_patch.py::TestRefusals::test_ambiguous_no_evidence_citation_is_refused`
covers that `patch.py` refuses to build a patch from this text, the same
way it already refuses an unresolved citation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts

_SHA_OLD = "b1b1b1b" + "1" * 33
_SHA_NEW = "c2c2c2c" + "2" * 33
_SHA_NEWEST = "d3d3d3d" + "3" * 33


def _ambiguous_trace(n_candidates):
    """A trace with `n_candidates` introduction_candidates and no evidence
    to say which one is real (1 to 3). `_SHA_OLD` is deliberately the
    chronologically oldest entry, so a fallback to
    `introduction_candidates[0]` would name it.
    """
    candidates = [
        {"sha": _SHA_OLD, "subject": "feat: add rate limiter",
         "date": "2020-01-01T00:00:00+00:00", "author": "Ryan",
         "author_email": "ryan@example.com", "why": "pickaxe"},
        {"sha": _SHA_NEW, "subject": "fix: adjust limiter threshold",
         "date": "2021-06-01T00:00:00+00:00", "author": "Choco",
         "author_email": "choco@example.com", "why": "pickaxe"},
        {"sha": _SHA_NEWEST, "subject": "fix: another limiter tweak",
         "date": "2022-03-01T00:00:00+00:00", "author": "Neo",
         "author_email": "neo@example.com", "why": "pickaxe"},
    ][:n_candidates]
    return {
        "target": {"path": "app/limiter.py", "start": 5, "end": 5},
        "introduction_candidates": candidates,
        "co_changed": [], "blame_candidates": [], "revert_chain": [], "notes": [],
        "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago"},
    }


class TestAmbiguousNoEvidenceIsADistinctHonestSentence(unittest.TestCase):
    def test_two_candidates_no_evidence_names_no_specific_candidate(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(2))
        self.assertNotIn(_SHA_OLD[:7], out)
        self.assertNotIn(_SHA_NEW[:7], out)
        self.assertNotIn("rate limiter", out)
        self.assertNotIn("limiter threshold", out)

    def test_two_candidates_no_evidence_names_the_candidate_count(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(2))
        self.assertIn("2", out)
        self.assertIn("as confirmed", out)
        self.assertIn("No commit was cited", out)

    def test_three_candidates_reports_three_not_a_stale_count(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(3))
        self.assertIn("3", out)
        self.assertNotIn(" 2 ", out)

    def test_does_not_claim_a_citation_was_made(self):
        # I1: reusing _unresolved_citation_text asserted "the verdict cites
        # commit {cited}" even though no citation was made at all, and the
        # missing-sha placeholder ("unknown"/"알 수 없음") leaked into the
        # sentence as if it were a real (if unverifiable) ref. Neither may
        # appear here: no citation was made, so there is nothing to call
        # unresolved or unknown.
        out = artifacts.skeleton("danger", _ambiguous_trace(2))
        self.assertNotIn("cites commit", out)
        self.assertNotIn("commit unknown", out)
        self.assertNotIn("unknown", out)

    def test_does_not_point_at_a_citation_to_check_by_hand(self):
        # unresolved.warning's remedy ("re-run the trace or check the
        # citation by hand") points at a citation that does not exist in
        # this branch; the remedy here has to be what actually recovers
        # this case instead.
        out = artifacts.skeleton("danger", _ambiguous_trace(2))
        self.assertNotIn("check the citation by hand", out)

    def test_none_and_empty_list_evidence_behave_the_same(self):
        self.assertEqual(
            artifacts.skeleton("danger", _ambiguous_trace(2), evidence=None),
            artifacts.skeleton("danger", _ambiguous_trace(2), evidence=[]),
        )

    def test_conditional_and_safe_grades_are_ambiguous_too(self):
        # _top's "ambiguous" branch does not key off grade except to
        # exempt "unknown" (see TestUnknownGradeKeepsGuessingTheOldestCandidate
        # below), so conditional and safe must refuse to guess as well.
        for grade in ("conditional", "safe"):
            with self.subTest(grade=grade):
                out = artifacts.skeleton(grade, _ambiguous_trace(2))
                self.assertNotIn(_SHA_OLD[:7], out)
                self.assertIn("as confirmed", out)
                self.assertIn("No commit was cited", out)

    def test_ko_names_no_specific_candidate_and_reports_the_count(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(2), lang="ko")
        self.assertNotIn(_SHA_OLD[:7], out)
        self.assertIn("2", out)
        self.assertIn("확정된 것으로 보지 마세요", out)
        self.assertNotIn("알 수 없음", out)


class TestSingleCandidateStillResolvesWithoutEvidence(unittest.TestCase):
    """The 69 fixtures already calling skeleton() with no evidence all have
    exactly one candidate; a single candidate is not ambiguous -- there is
    nothing else it could be -- so this boundary must keep citing it."""

    def test_single_candidate_no_evidence_still_cites_it(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(1))
        self.assertIn(_SHA_OLD[:7], out)
        self.assertIn("rate limiter", out)


class TestUnknownGradeKeepsGuessingTheOldestCandidate(unittest.TestCase):
    """unknown's own wording already says "closest commit" and flags the
    investigation as inconclusive, so guessing the oldest candidate there
    is the same honest fallback it always was, not a new confident wrong
    answer -- see _top's "ambiguous" branch for why grade "unknown" is
    exempt."""

    def test_unknown_grade_still_names_the_oldest_candidate(self):
        out = artifacts.skeleton("unknown", _ambiguous_trace(2))
        self.assertIn(_SHA_OLD[:7], out)
        self.assertIn("rate limiter", out)


if __name__ == "__main__":
    unittest.main()
