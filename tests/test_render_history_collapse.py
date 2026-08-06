"""Regression tests for the verdict-first report layout (v02 work item 1).

Two behaviors are pinned here:

1. Section order: badge, then summary, then conditions (styled as a
   checklist), then evidence, then the next-step artifact, and only then
   History; the reader's question is "can I delete it", and History is
   supporting evidence for that answer, not the headline.
2. History collapsing: when a trace carries more history rows than
   `render._HISTORY_COLLAPSE_THRESHOLD`, everything the verdict cites as
   real, everything `blame_candidates` found (real, noise, or plain), and
   the revert chain stay visible outside a `<details>` element; every other
   candidate (pickaxe/line-history hits that are neither cited nor part of
   blame's own output) folds into that `<details>`, labeled with a count.
   Short traces (at or under the threshold) render exactly as before:
   nothing collapses.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import render


def _sha(prefix):
    return (prefix + "0" * 40)[:40]


REAL_SHA = _sha("a1a1a1a")
BLAME_NOISE_SHA = _sha("b2b2b2b")
REVERT_SHA = _sha("c3c3c3c")
OTHER_SHAS = [_sha("d{}d{}d".format(i, i)) for i in range(15)]


def _long_trace():
    return {
        "target": {"path": "big.py", "start": 10, "end": 10},
        "blame_candidates": [
            {"sha": REAL_SHA, "subject": "fix: the real introduction",
             "date": "2019-01-01T00:00:00+00:00", "author": "Kim",
             "noise": {"is_noise": False, "category": "", "confidence": 0.0,
                       "signals": []}},
            {"sha": BLAME_NOISE_SHA, "subject": "chore: apply formatter",
             "date": "2023-01-01T00:00:00+00:00", "author": "Bot",
             "noise": {"is_noise": True, "category": "N1", "confidence": 0.8,
                       "signals": ["diff is empty when whitespace is ignored"]}},
        ],
        "introduction_candidates": [
            {"sha": REAL_SHA, "why": "blame",
             "subject": "fix: the real introduction",
             "date": "2019-01-01T00:00:00+00:00", "author": "Kim",
             "author_email": "kim@example.com", "files_changed": 1},
        ] + [
            {"sha": sha, "why": "pickaxe",
             "subject": "chore: unrelated commit {}".format(i),
             "date": "2020-0{}-01T00:00:00+00:00".format((i % 9) + 1),
             "author": "Someone", "author_email": "someone@example.com",
             "files_changed": 1}
            for i, sha in enumerate(OTHER_SHAS)
        ],
        "revert_chain": [
            {"sha": REVERT_SHA, "subject": 'Revert "something unrelated"',
             "date": "2021-01-01T00:00:00+00:00", "author": "Kim"},
        ],
        "co_changed": [],
        "limits": {"max_commits": 5000, "since": None, "truncated": False,
                   "max_candidates": 200, "candidate_cap_reached": False},
        "notes": [],
    }


def _long_verdict():
    return {
        "grade": "conditional",
        "summary": "Looks load-bearing; verify before deleting.",
        "evidence": [{"type": "commit", "ref": REAL_SHA[:7], "note": "the real fix"}],
        "conditions": ["Check for callers in the admin panel",
                       "Confirm the feature flag is fully rolled out"],
        "artifact": {"kind": "keep-comment", "content": "// KEEP: see above"},
    }


class TestSectionOrder(unittest.TestCase):
    def setUp(self):
        self.html = render.render(_long_trace(), _long_verdict())

    def test_badge_then_summary_then_conditions_then_evidence_then_artifact_then_history(self):
        badge_pos = self.html.index('class="badge"')
        summary_pos = self.html.index('class="sub"')
        conditions_pos = self.html.index("Conditions")
        evidence_pos = self.html.index("<strong>Evidence</strong>")
        artifact_pos = self.html.index("Next step (")
        history_pos = self.html.index("History: blame vs. the real introduction")
        notes_pos = self.html.index("Notes and limits")
        self.assertTrue(
            badge_pos < summary_pos < conditions_pos < evidence_pos
            < artifact_pos < history_pos < notes_pos,
            "expected badge < summary < conditions < evidence < artifact "
            "< history < notes, positions were: {}".format(
                (badge_pos, summary_pos, conditions_pos, evidence_pos,
                 artifact_pos, history_pos, notes_pos)))

    def test_conditions_render_as_a_checklist(self):
        self.assertIn('class="checklist"', self.html)
        self.assertIn("Check for callers in the admin panel", self.html)


class TestHistoryCollapseLongTrace(unittest.TestCase):
    def setUp(self):
        self.html = render.render(_long_trace(), _long_verdict())

    def test_details_element_present(self):
        self.assertIn("<details", self.html)
        self.assertIn("</details>", self.html)

    def test_summary_states_the_correct_count(self):
        # 15 pickaxe-only commits are neither cited as real, nor part of
        # blame_candidates, nor part of the revert chain, so all 15 (and
        # only those 15) must fold into the collapsed section.
        self.assertIn("Other candidates from the search (15 commits)", self.html)

    def test_real_row_is_outside_details(self):
        details_pos = self.html.index("<details")
        real_marker = self.html.index('fix: the real introduction')
        self.assertLess(real_marker, details_pos,
                         "the cited real commit must render outside <details>")

    def test_blame_noise_row_is_outside_details(self):
        details_pos = self.html.index("<details")
        noise_marker = self.html.index("chore: apply formatter")
        self.assertLess(noise_marker, details_pos,
                         "every blame_candidates row must render outside <details>")

    def test_revert_row_is_outside_details(self):
        details_pos = self.html.index("<details")
        revert_marker = self.html.index('Revert &quot;something unrelated&quot;')
        self.assertLess(revert_marker, details_pos,
                         "the revert chain must render outside <details>")

    def test_an_unrelated_pickaxe_row_is_inside_details(self):
        details_pos = self.html.index("<details")
        other_marker = self.html.index("chore: unrelated commit 0")
        self.assertGreater(other_marker, details_pos,
                            "a candidate cited by nothing and not found via "
                            "blame must fold into <details>")

    def test_summary_is_clickable_and_focusable(self):
        self.assertIn("cursor:pointer", self.html)
        self.assertIn("focus-visible", self.html)


class TestHistoryDoesNotCollapseWhenShort(unittest.TestCase):
    def test_short_trace_has_no_details_element(self):
        trace_data = {
            "target": {"path": "small.py", "start": 3, "end": 3},
            "blame_candidates": [{
                "sha": REAL_SHA, "subject": "fix: the real introduction",
                "date": "2019-01-01T00:00:00+00:00", "author": "Kim",
                "noise": {"is_noise": False, "category": "", "confidence": 0.0,
                          "signals": []},
            }],
            "introduction_candidates": [{
                "sha": REAL_SHA, "why": "blame",
                "subject": "fix: the real introduction",
                "date": "2019-01-01T00:00:00+00:00", "author": "Kim",
                "author_email": "kim@example.com", "files_changed": 1,
            }],
            "revert_chain": [],
            "co_changed": [],
            "limits": {"max_commits": 5000, "since": None, "truncated": False,
                       "max_candidates": 200, "candidate_cap_reached": False},
            "notes": [],
        }
        verdict = {
            "grade": "danger", "summary": "Do not delete.",
            "evidence": [{"type": "commit", "ref": REAL_SHA[:7]}],
            "conditions": [],
            "artifact": {"kind": "keep-comment", "content": "// KEEP"},
        }
        html = render.render(trace_data, verdict)
        self.assertNotIn("<details", html)
        self.assertNotIn("Other candidates from the search", html)


if __name__ == "__main__":
    unittest.main()
