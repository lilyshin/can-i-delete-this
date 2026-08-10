"""Regression tests for the blame_candidates citation gap.

The previous fix wave established that the verdict's `evidence[].ref`
decides which commit is the real introduction, and implemented that
against `introduction_candidates` only. That collides with what the same
fix wave taught agents to do: SKILL.md's workflow and noise-catalog.md's
N10 entry both instruct an agent to read a noise-flagged commit's own diff
with `git show <sha> -- <path>` and cite it when the diff is what actually
added the target lines. Noise filtering removes that commit from
`introduction_candidates` before the verdict is ever written (see
trace.py's `add()`, which returns early on `v.is_noise`), so the only place
left to find a cited N10 squash commit is `blame_candidates`.

Before the fix: render.py struck such a citation through as noise (bold
"real" and struck-through "noise" never met in the same evidence-aware
code path), and artifacts.py's `_top()` searched only
`introduction_candidates`, so it found nothing and printed "reason
unknown" for a verdict with a perfectly good citation. A second, related
bug lived in the same function: when a citation matched nothing in either
list at all (a stale or mistyped ref -- verdict.py's schema only checks
that a ref is a non-empty string, not that it names a real commit), `_top`
silently substituted `introduction_candidates[0]`, which is exactly the M2
misattribution the previous fix wave was meant to eliminate, resurfacing
through this unguarded fallback path.

citation.py now resolves a citation across both candidate lists in one
place, and render.py/artifacts.py both use it. These tests build the real
F4 and F5 fixtures with the actual git CLI (not hand-written JSON) and pin
the three behaviors the fix is responsible for.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import artifacts
import render
import trace as tracer


def _verdict_citing(ref, grade="danger"):
    return {
        "grade": grade,
        "summary": "Regression check: verdict cites {}.".format(ref),
        "evidence": [{"type": "commit", "ref": ref, "note": "test citation"}],
        "conditions": [],
        "artifact": {"kind": "keep-comment", "content": "// KEEP: placeholder"},
    }


def _rows_mentioning(html, sha):
    """Every top-level timeline row div whose text mentions `sha`."""
    return [m.group(0) for m in re.finditer(r'<div class="row[^"]*">.*?</div></div>', html)
            if sha[:7] in m.group(0)]


class TestBlameOnlyCitation(unittest.TestCase):
    """F4: the real commit is a squash (N10). Noise filtering drops it out
    of introduction_candidates entirely, leaving it only in
    blame_candidates, flagged is_noise. A verdict that cites it anyway
    (per the diff-reading route SKILL.md and noise-catalog.md's N10 entry
    teach) must be honored by both render.py and artifacts.py.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f4(self.tmp.name)
        self.trace = tracer.trace(self.info["repo"], self.info["path"],
                                   self.info["line"], self.info["line"])

    def test_premise_real_commit_is_blame_only_and_noise_flagged(self):
        """Pin the setup: if trace.py or noise.py change so this commit
        starts showing up in introduction_candidates, or stops being
        flagged noise, this fixture no longer exercises the bug and the
        tests below would pass for the wrong reason.
        """
        self.assertEqual(self.trace["introduction_candidates"], [])
        self.assertEqual(len(self.trace["blame_candidates"]), 1)
        blamed = self.trace["blame_candidates"][0]
        self.assertEqual(blamed["sha"], self.info["real_sha"])
        self.assertTrue(blamed["noise"]["is_noise"])
        self.assertEqual(blamed["noise"]["category"], "N10")

    def test_render_marks_the_cited_blame_only_commit_real(self):
        verdict = _verdict_citing(self.info["real_sha"][:7])
        html = render.render(self.trace, verdict)
        rows = _rows_mentioning(html, self.info["real_sha"])
        self.assertEqual(len(rows), 1, "the cited commit must appear exactly once")
        self.assertIn('class="row real"', rows[0])
        self.assertIn('class="tag real">real introduction', rows[0])

    def test_render_still_surfaces_the_noise_category_on_the_real_row(self):
        """"Real introduction" and "also noise" are not a contradiction to
        pick between: this is exactly the N10 situation noise-catalog.md
        documents, and the page should say both, on the one row.
        """
        verdict = _verdict_citing(self.info["real_sha"][:7])
        html = render.render(self.trace, verdict)
        rows = _rows_mentioning(html, self.info["real_sha"])
        self.assertIn("N10", rows[0])

    def test_cited_commit_never_gets_a_separate_noise_row(self):
        verdict = _verdict_citing(self.info["real_sha"][:7])
        html = render.render(self.trace, verdict)
        rows = _rows_mentioning(html, self.info["real_sha"])
        self.assertEqual(len(rows), 1)
        self.assertNotIn('class="row noise"', rows[0])

    def test_artifact_names_the_cited_commit_not_reason_unknown(self):
        verdict = _verdict_citing(self.info["real_sha"][:7])
        out = artifacts.skeleton(verdict["grade"], self.trace, verdict["evidence"])
        self.assertIn(self.info["real_sha"][:7], out)
        self.assertIn("Rotate token on idle sessions", out)
        self.assertNotIn("reason unknown", out)


class TestUnresolvedCitation(unittest.TestCase):
    """A verdict can pass verdict.py's schema (which only checks that a
    ref is a non-empty string) while citing a commit that matches nothing
    in this trace at all -- a stale or mistyped ref. artifacts.py must say
    so plainly, not silently fall back to introduction_candidates[0]: that
    fallback is exactly the M2 misattribution the previous fix wave was
    meant to eliminate.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f5(self.tmp.name)
        self.trace = tracer.trace(self.info["repo"], self.info["path"],
                                   self.info["line"], self.info["line"])
        self.oldest = self.trace["introduction_candidates"][0]

    def test_premise_oldest_candidate_is_not_the_real_commit(self):
        self.assertNotEqual(self.oldest["sha"], self.info["real_sha"])

    def test_bogus_ref_does_not_name_the_oldest_candidate(self):
        verdict = _verdict_citing("deadbee")
        out = artifacts.skeleton(verdict["grade"], self.trace, verdict["evidence"])
        self.assertNotIn(self.oldest["sha"][:7], out)
        self.assertNotIn(self.oldest["subject"], out)

    def test_bogus_ref_states_the_citation_did_not_resolve(self):
        verdict = _verdict_citing("deadbee")
        out = artifacts.skeleton(verdict["grade"], self.trace, verdict["evidence"])
        self.assertIn("deadbee", out)
        self.assertTrue(
            "could not" in out.lower() or "not found" in out.lower()
            or "not resolve" in out.lower() or "unresolved" in out.lower(),
            "artifact text must plainly say the citation did not resolve, "
            "got: {!r}".format(out))

    def test_no_citation_and_no_candidates_still_says_reason_unknown(self):
        """The "unresolved citation" text must not swallow the genuinely
        empty case: no citation at all, and introduction_candidates empty
        too, is still the honest "reason unknown" this project already
        prints for F4-style traces with no evidence to check.
        """
        empty_trace = {
            "target": {"path": "legacy.py", "start": 10, "end": 12},
            "introduction_candidates": [], "co_changed": [],
            "blame_candidates": [], "revert_chain": [], "notes": [],
            "limits": {"truncated": False, "max_commits": 5000,
                       "since": "5 years ago", "candidate_cap_reached": False},
        }
        out = artifacts.skeleton("danger", empty_trace)
        self.assertIn("reason unknown", out)


class TestExplicitlyIncludedCommit(unittest.TestCase):
    """0.2.1 regression, corrected design: a commit an agent finds by
    reading history directly, that trace.py's own searches (blame, pickaxe,
    line-history) never surfaced, must still be able to render and produce
    an artifact naming it -- but the fact of what that commit *is* must
    come from git, never from the verdict's own evidence text. An agent can
    type anything into an evidence item's `note` (or any other field); a
    fabricated subject on a real, cited commit must not leak into the
    report just because it happened to be typed there. See
    TestFabricatedCitationIsRejected below for the sibling regression: a
    fabricated subject on a commit that does not exist at all.

    The fix routes through trace.py, not citation.py: `--include-commit
    <sha>` (`include_commits=[...]` in trace()) looks the sha up with
    `gitq.commit_meta` against the real repository and, once verified, adds
    it to `introduction_candidates` with `why: "cited"`. citation.py itself
    is back to matching only `introduction_candidates` and
    `blame_candidates`, exactly as it was before this correction: no third
    source, no reading of evidence-supplied descriptive fields anywhere.

    Uses the real F4 fixture (a squash commit, N10-flagged, so by default
    `introduction_candidates` comes up empty) for two things at once:
    proving an explicitly included commit that noise filtering would
    otherwise exclude still becomes a candidate, and proving its rendered
    subject/date/author come from git even when the verdict's own evidence
    carries a different, fabricated subject alongside the real ref.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f4(self.tmp.name)

    def test_include_commit_surfaces_a_noise_filtered_commit(self):
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"],
                               include_commits=[self.info["real_sha"]])
        cand = next((c for c in result["introduction_candidates"]
                     if c["sha"] == self.info["real_sha"]), None)
        self.assertIsNotNone(cand, "explicitly included commit must become a candidate")
        self.assertEqual(cand["why"], "cited")
        self.assertEqual(cand["subject"],
                         "Rotate token on idle sessions and reformat module (#2211)")

    def test_render_and_artifact_use_git_metadata_not_the_evidence_note(self):
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"],
                               include_commits=[self.info["real_sha"]])
        verdict = {
            "grade": "danger",
            "summary": "Found by reading history directly; blame and pickaxe missed it.",
            "evidence": [{
                "type": "commit", "ref": self.info["real_sha"][:7],
                "note": "found via git log -p --follow, not the tracer",
                # Deliberately a different, fabricated subject: this must
                # never win over the real git subject once the commit is
                # verified through --include-commit.
                "subject": "haxxor: totally fake subject",
            }],
            "conditions": [],
            "artifact": {"kind": "keep-comment", "content": "// KEEP: placeholder"},
        }
        html = render.render(result, verdict)
        rows = _rows_mentioning(html, self.info["real_sha"])
        self.assertEqual(len(rows), 1)
        self.assertIn('class="row real"', rows[0])
        self.assertIn("Rotate token on idle sessions", rows[0])
        self.assertNotIn("totally fake subject", rows[0])

        out = artifacts.skeleton(verdict["grade"], result, verdict["evidence"])
        self.assertIn(self.info["real_sha"][:7], out)
        self.assertIn("Rotate token on idle sessions", out)
        self.assertNotIn("totally fake subject", out)


class TestFabricatedCitationIsRejected(unittest.TestCase):
    """The exact scenario reported against the 0.2.1 draft: a nonexistent
    sha ("deadbee") cited with a fully fabricated subject/date/author.
    Without --include-commit ever verifying it against the repository,
    this must resolve exactly like any other unresolved citation: no
    candidate, no row, and the fabricated subject must not appear anywhere
    in the report or the artifact.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f1(self.tmp.name)
        self.trace = tracer.trace(self.info["repo"], self.info["path"],
                                   self.info["line"], self.info["line"])
        self.evidence = [{
            "type": "commit", "ref": "deadbee", "note": "보안 수정",
            "subject": "fix: patch critical auth bypass (#9999)",
            "date": "2021-01-01T00:00:00+09:00", "author": "Ghost",
        }]

    def test_fabricated_sha_produces_no_candidate_via_trace(self):
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"],
                               include_commits=["deadbee"])
        shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertNotIn("deadbee", shas)
        self.assertTrue(
            any("deadbee" in n for n in result["notes"]),
            "a nonexistent --include-commit sha must be noted, not silently dropped")

    def test_render_does_not_show_the_fabricated_subject(self):
        verdict = {
            "grade": "danger", "summary": "fabricated citation",
            "evidence": self.evidence, "conditions": [],
            "artifact": {"kind": "keep-comment", "content": "// KEEP: placeholder"},
        }
        html = render.render(self.trace, verdict)
        self.assertNotIn("patch critical auth bypass", html)
        self.assertNotIn('class="row real"', html)

    def test_artifact_does_not_name_the_fabricated_commit(self):
        out = artifacts.skeleton("danger", self.trace, self.evidence)
        self.assertNotIn("patch critical auth bypass", out)
        self.assertTrue(
            "could not" in out.lower() or "not found" in out.lower()
            or "not resolve" in out.lower() or "unresolved" in out.lower())


class TestNoDuplicateRow(unittest.TestCase):
    """F5's reintroduction commit is discoverable straight through blame
    (trace.py's own `add()` folds a non-noise blame result into
    introduction_candidates too, tagging it why="blame"), so it lives in
    both candidate lists, AND its subject ("reapply") also qualifies it
    for revert_chain. A commit the verdict cites is the answer and must
    appear exactly once, not once per list that happens to contain it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f5(self.tmp.name)
        self.trace = tracer.trace(self.info["repo"], self.info["path"],
                                   self.info["line"], self.info["line"])

    def test_premise_real_commit_is_in_both_lists_and_the_revert_chain(self):
        real_sha = self.info["real_sha"]
        intro_shas = {c["sha"] for c in self.trace["introduction_candidates"]}
        blame_shas = {b["sha"] for b in self.trace["blame_candidates"]}
        revert_shas = {r["sha"] for r in self.trace["revert_chain"]}
        self.assertIn(real_sha, intro_shas)
        self.assertIn(real_sha, blame_shas)
        self.assertIn(real_sha, revert_shas)

    def test_cited_commit_appears_in_exactly_one_row(self):
        verdict = _verdict_citing(self.info["real_sha"][:7])
        html = render.render(self.trace, verdict)
        rows = _rows_mentioning(html, self.info["real_sha"])
        self.assertEqual(len(rows), 1,
                          "expected exactly one row for the cited commit, got: {}".format(rows))
        self.assertIn('class="row real"', rows[0])


if __name__ == "__main__":
    unittest.main()
