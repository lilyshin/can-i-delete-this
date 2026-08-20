"""Regression test for the second 0.9.2 field finding: calling
`artifacts.skeleton()` with no `evidence` against a real trace that had 7
`introduction_candidates` produced a confident KEEP comment citing the
first candidate -- a 2020 commit unrelated to the target. `_top`'s
"fallback" branch cannot tell candidates apart without a citation, and
before this fix it picked the chronologically oldest one anyway whenever
`introduction_candidates` was non-empty, for any count at all.

Both production call sites (`patch.py`, and `artifacts.py`'s own CLI) pass
`evidence` from a verdict `verdict.validate` has already checked, so this
gap never fires there; it only fires when a caller invokes `skeleton()`
directly with no evidence at all, which is exactly what happened during
the 0.9.2 field run this test reproduces.

The fix routes this case through the same "citation could not be
verified" text an unresolved citation already gets (see `_top`'s
"unresolved" branch and `_unresolved_citation_text`), rather than a new
string: both situations leave the reader in the same place -- no
candidate named, and the grade must not be treated as confirmed.
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


def _ambiguous_trace(n_candidates):
    """A trace with `n_candidates` introduction_candidates and no evidence
    to say which one is real. `n_candidates` clamps to 2, the shape that
    matters here: `_SHA_OLD` is deliberately the chronologically oldest
    entry, so a fallback to `introduction_candidates[0]` would name it.
    """
    candidates = [
        {"sha": _SHA_OLD, "subject": "feat: add rate limiter",
         "date": "2020-01-01T00:00:00+00:00", "author": "Ryan",
         "author_email": "ryan@example.com", "why": "pickaxe"},
        {"sha": _SHA_NEW, "subject": "fix: adjust limiter threshold",
         "date": "2021-06-01T00:00:00+00:00", "author": "Choco",
         "author_email": "choco@example.com", "why": "pickaxe"},
    ][:n_candidates]
    return {
        "target": {"path": "app/limiter.py", "start": 5, "end": 5},
        "introduction_candidates": candidates,
        "co_changed": [], "blame_candidates": [], "revert_chain": [], "notes": [],
        "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago"},
    }


class TestAmbiguousNoEvidenceIsUnresolvedNotAGuess(unittest.TestCase):
    def test_two_candidates_no_evidence_names_no_specific_candidate(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(2))
        self.assertNotIn(_SHA_OLD[:7], out)
        self.assertNotIn(_SHA_NEW[:7], out)
        self.assertNotIn("rate limiter", out)
        self.assertNotIn("limiter threshold", out)

    def test_two_candidates_no_evidence_carries_the_unresolved_warning(self):
        out = artifacts.skeleton("danger", _ambiguous_trace(2))
        self.assertIn("could not be verified", out)

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
                self.assertIn("could not be verified", out)


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
