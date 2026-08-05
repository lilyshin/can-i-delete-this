"""Regression tests for the final-review M1/M2 fix.

M1: render.py used to send every blame_candidates entry to _noise_row
regardless of noise.is_noise, and bolded every introduction_candidates
entry as "real", with no reference to what the verdict actually cited.
M2: artifacts.py's _top() and trace.py's co_changed both treated
introduction_candidates[0] as "the" introducing commit, but trace.py sorts
candidates chronologically (oldest first), not by which one is real. An
older commit can share a pickaxe token with the target line without being
the commit that introduced it, and three of this project's five committed
fixtures (build_f5, build_f7, build_deep_history) demonstrate exactly that.

These tests build those three fixtures for real, run the real tracer, write
a verdict that cites the actual introducing commit as evidence, and assert
that both render.py and artifacts.py attribute to that cited commit, not to
whichever candidate happens to sort first.
"""

import html as html_module
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


def _verdict_citing(sha, subject):
    return {
        "grade": "danger",
        "summary": "Regression check: verdict cites {}.".format(sha[:7]),
        "evidence": [{"type": "commit", "ref": sha[:7],
                      "note": "the commit that actually introduced this"}],
        "conditions": [],
        "artifact": {"kind": "keep-comment",
                     "content": "// KEEP: {} ({})".format(subject, sha[:7])},
    }


class OlderTokenCollisionCase:
    """Shared checks for a fixture where an older, non-introducing commit
    shares a pickaxe token with the target line and therefore does not sort
    to introduction_candidates[0] by accident of construction."""

    builder = None

    def build(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        info = getattr(make_fixture_repo, self.builder)(self.tmp.name)
        result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        return info, result

    def test_oldest_candidate_is_not_the_real_commit(self):
        """Pin the premise: index 0 is not the real commit for this fixture,
        so any code that reads position 0 as meaning "real" gets this wrong.
        """
        info, result = self.build()
        cands = result["introduction_candidates"]
        self.assertGreater(len(cands), 1, "fixture must offer more than one candidate")
        self.assertNotEqual(cands[0]["sha"], info["real_sha"],
                             "fixture no longer exercises the position-vs-meaning bug")
        shas = [c["sha"] for c in cands]
        self.assertIn(info["real_sha"], shas)

    def test_render_marks_only_the_cited_commit_as_real(self):
        info, result = self.build()
        real_sha = info["real_sha"]
        real_subject = next(c["subject"] for c in result["introduction_candidates"]
                             if c["sha"] == real_sha)
        verdict = _verdict_citing(real_sha, real_subject)
        html = render.render(result, verdict)

        real_row_marker = '<span class="subject">{} {}'.format(
            real_sha[:7], html_module.escape(real_subject, quote=True))
        self.assertIn(real_row_marker, html)
        # The row for the real commit must carry the "real" tag and class.
        real_row_start = html.index(real_row_marker)
        # Walk back to the start of this row's enclosing div to check its class.
        row_open = html.rfind('<div class="row', 0, real_row_start)
        row_chunk = html[row_open:real_row_start]
        self.assertIn('class="row real"', row_chunk)

        # Every other introduction candidate must NOT be tagged real, and a
        # blame candidate that isn't actually noise must not be struck
        # through either (the exact M1 bug: a non-noise commit rendered
        # both bold-real and struck-through simultaneously).
        for c in result["introduction_candidates"]:
            if c["sha"] == real_sha:
                continue
            marker = '<span class="subject">{} {}'.format(
                c["sha"][:7], html_module.escape(c["subject"], quote=True))
            self.assertIn(marker, html)
            pos = html.index(marker)
            row_open = html.rfind('<div class="row', 0, pos)
            row_chunk = html[row_open:pos]
            self.assertNotIn('class="row real"', row_chunk,
                              "an uncited candidate must not be tagged real")

        for b in result["blame_candidates"]:
            if b["sha"] == real_sha:
                continue
            marker = '<span class="subject">{} {}'.format(
                b["sha"][:7], html_module.escape(b["subject"], quote=True))
            self.assertIn(marker, html)
            pos = html.index(marker)
            row_open = html.rfind('<div class="row', 0, pos)
            row_chunk = html[row_open:pos]
            if not b["noise"]["is_noise"]:
                self.assertNotIn('class="row noise"', row_chunk,
                                  "a blame candidate that scored as not-noise "
                                  "must not be struck through as noise")

    def test_artifact_skeleton_cites_the_verdicts_commit_not_the_oldest(self):
        info, result = self.build()
        real_sha = info["real_sha"]
        real_subject = next(c["subject"] for c in result["introduction_candidates"]
                             if c["sha"] == real_sha)
        oldest = result["introduction_candidates"][0]
        verdict = _verdict_citing(real_sha, real_subject)

        out = artifacts.skeleton(verdict["grade"], result, verdict["evidence"])
        self.assertIn(real_sha[:7], out)
        if oldest["sha"] != real_sha:
            self.assertNotIn(oldest["sha"][:7], out)


class TestDeepHistoryOlderTokenCollision(OlderTokenCollisionCase, unittest.TestCase):
    builder = "build_deep_history"


class TestF5OlderTokenCollision(OlderTokenCollisionCase, unittest.TestCase):
    builder = "build_f5"


class TestF7OlderTokenCollision(OlderTokenCollisionCase, unittest.TestCase):
    builder = "build_f7"


if __name__ == "__main__":
    unittest.main()
