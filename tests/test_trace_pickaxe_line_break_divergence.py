"""Regression tests for the fifth fix round: `trace.py`'s pickaxe needle
selection shares the exact line-break-divergence hazard `patch.py` and
`scan.py` already closed, and the team lead's reading of its severity is
right, confirmed here by reproduction rather than deferred to: a needle
sliced from the wrong line by the shift is not a weaker search, it is a
token from code the target has nothing to do with, and pickaxe finding
a commit that touched *that* token adds it to `introduction_candidates`
with `why: "pickaxe"` -- indistinguishable from a genuine hit, and
citable in a verdict. `TestPickaxeReachesAWrongAttributionWithoutTheGuard`
below proves the contamination reaches a candidate, not just a weaker
search, before the positive-case tests confirm the guard added this round
prevents it.

Unlike `patch.py` (refuses to build a patch) or `scan.py` (skips the
file), there is no single artifact or file-level result to refuse or
skip here: the fix is narrower, dropping only the pickaxe search path
for this one target while leaving blame and line-history, which are
unaffected (neither passes a Python-sliced line to anything; both hand
`start`/`end` straight to git's own `-L` flag), to search as normal.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import gitq
import make_fixture_repo
import trace as tracer


class TestPickaxeReachesAWrongAttributionWithoutTheGuard(unittest.TestCase):
    """Proof the hazard is real before the fix's own tests confirm it is
    closed: pickaxe, searching for the token a line-shifted read would
    hand it, finds a commit that has nothing to do with the target."""

    def test_wrong_line_token_reaches_the_unrelated_commit_via_pickaxe(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_pickaxe_wrong_line_attribution(
                tmp, divergent=b"\r")
            shas = gitq.pickaxe(info["repo"], "SPURIOUS_TOKEN_ABCDEFGH")
        self.assertIn(info["spurious_sha"], shas,
                     "premise: the wrong-line token really does reach an "
                     "unrelated commit through pickaxe")


class TestPickaxeSkippedOnDivergenceDoesNotMisattribute(unittest.TestCase):
    """Each case first proves what pickaxe would find if it ran on the
    wrong-line token (tying the "no misattribution" assertion to a
    concrete wrong sha, not just a counter), then confirms `trace()`
    itself never lets that sha reach `introduction_candidates`.
    """

    def _assert_pickaxe_skipped_not_misattributed(self, divergent):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_pickaxe_wrong_line_attribution(
                tmp, divergent=divergent)

            # Premise: pickaxe would reach the unrelated commit if handed
            # the wrong-line token, the same reproduction
            # TestPickaxeReachesAWrongAttributionWithoutTheGuard pins
            # directly against the predicate-free pickaxe call.
            spurious_hits = gitq.pickaxe(info["repo"], "SPURIOUS_TOKEN_ABCDEFGH")
            self.assertIn(info["spurious_sha"], spurious_hits,
                         "premise: the planted token really does reach "
                         "the unrelated commit")

            result = tracer.trace(info["repo"], info["path"],
                                  info["line"], info["line"])

        # Checked before the limits flag or notes, deliberately: a
        # mutation that removes the guard must fail here, on the
        # spurious commit reappearing in introduction_candidates (the
        # exact sha the premise above just proved pickaxe would find),
        # not merely on a flag reading False.
        candidate_shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertNotIn(
            info["spurious_sha"], candidate_shas,
            "the unrelated commit the premise proved pickaxe would find "
            "must not reach introduction_candidates")
        self.assertTrue(result["limits"]["pickaxe_skipped_irregular_line_break"],
                        result["limits"])
        self.assertTrue(
            any("pickaxe" in n and "skip" in n for n in result["notes"]),
            result["notes"])
        self.assertNotIn("pickaxe", [c["kind"] for c in result["commands"]])

    def test_lone_cr_skips_pickaxe(self):
        self._assert_pickaxe_skipped_not_misattributed(b"\r")

    def test_vertical_tab_skips_pickaxe(self):
        # One representative of the other eight always-break characters,
        # the same standard test_scan_line_break_divergence.py applies;
        # all nine are covered at the predicate level by
        # test_trace_line_break_divergence.py.
        self._assert_pickaxe_skipped_not_misattributed(b"\x0b")


class TestNegativeControlsStillRunPickaxeNormally(unittest.TestCase):
    """Neither a CRLF-only file nor a plain LF file may lose their
    pickaxe search: doing so would silently weaken search for every
    Windows-authored file, or every ordinary one, for no reason at all.
    """

    def _assert_pickaxe_runs_and_finds_candidates(self, divergent):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_pickaxe_wrong_line_attribution(
                tmp, divergent=divergent)
            result = tracer.trace(info["repo"], info["path"],
                                  info["line"], info["line"])
        self.assertFalse(result["limits"]["pickaxe_skipped_irregular_line_break"],
                         result["limits"])
        self.assertIn("pickaxe", [c["kind"] for c in result["commands"]])
        # The real target commit itself must still be found (by whatever
        # search path), and the unrelated commit must not be, since
        # nothing plants its token at the real target's own line here.
        candidate_shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertIn(info["sha"], candidate_shas)
        self.assertNotIn(info["spurious_sha"], candidate_shas)

    def test_crlf_file_still_runs_pickaxe(self):
        self._assert_pickaxe_runs_and_finds_candidates(b"\r\n")

    def test_plain_lf_file_still_runs_pickaxe(self):
        self._assert_pickaxe_runs_and_finds_candidates(b"")


if __name__ == "__main__":
    unittest.main()
