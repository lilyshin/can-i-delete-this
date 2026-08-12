"""Regression tests for evidence roles (v0.5.0): the lifetime arc, the
isolation figures, and the risk block render.py draws from `role`-tagged
evidence items (see verdict.py's `EVIDENCE_ROLES`).

Reuses the same small trace fixture every other render test file uses
(TRACE-shaped: target/blame_candidates/introduction_candidates/revert_chain/
co_changed/limits/notes) rather than building a real repository, since none
of these tests need git at all -- they only exercise render.py's pure
string-building functions against hand-built dicts.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import render


TRACE = {
    "target": {"path": "payment.py", "start": 3, "end": 3},
    "blame_candidates": [],
    "introduction_candidates": [{
        "sha": "a3f8c21" + "0" * 33, "why": "blame",
        "subject": "hotfix: prevent double charge (#4127)",
        "date": "2019-11-08T02:14:00+00:00", "author": "Kim",
        "author_email": "kim@example.com", "files_changed": 1,
    }],
    "revert_chain": [],
    "co_changed": [],
    "limits": {"max_commits": 5000, "since": "5 years ago", "truncated": False,
               "max_candidates": 200, "candidate_cap_reached": False},
    "notes": [],
}


def verdict_with(evidence, grade="safe"):
    return {
        "grade": grade,
        "summary": "The reason this existed no longer applies.",
        "evidence": evidence,
        "conditions": [],
        "artifact": {"kind": "pr-body" if grade == "safe" else "keep-comment",
                     "content": "delete away"},
    }


NO_ROLE_EVIDENCE = [{"type": "commit", "ref": "a3f8c21", "note": "the only evidence"}]

BOTH_ROLES_EVIDENCE = [
    {"type": "commit", "ref": "a3f8c21", "role": "introduced",
     "note": "added in 2023 to work around the old sync path"},
    {"type": "commit", "ref": "b91c440", "role": "superseded",
     "note": "2026 refactor removed the only call site"},
]

INTRODUCED_ONLY_EVIDENCE = [
    {"type": "commit", "ref": "a3f8c21", "role": "introduced", "note": "added in 2023"},
]

SUPERSEDED_ONLY_EVIDENCE = [
    {"type": "commit", "ref": "a3f8c21", "note": "still need a commit ref for the grade"},
    {"type": "commit", "ref": "b91c440", "role": "superseded", "note": "retired in 2026"},
]


class TestLifecycleArc(unittest.TestCase):
    def test_renders_with_both_roles(self):
        html = render.render(TRACE, verdict_with(BOTH_ROLES_EVIDENCE))
        self.assertIn("Why it existed", html)
        self.assertIn("Introduced", html)
        self.assertIn("Superseded", html)
        self.assertIn("a3f8c21", html)
        self.assertIn("b91c440", html)
        self.assertIn("arc-arrow", html)

    def test_renders_with_only_introduced(self):
        html = render.render(TRACE, verdict_with(INTRODUCED_ONLY_EVIDENCE))
        self.assertIn("Why it existed", html)
        self.assertIn("Introduced", html)
        self.assertNotIn("Superseded", html)

    def test_renders_with_only_superseded(self):
        html = render.render(TRACE, verdict_with(SUPERSEDED_ONLY_EVIDENCE))
        self.assertIn("Why it existed", html)
        self.assertIn("Superseded", html)
        self.assertNotIn(">Introduced<", html)

    def test_absent_when_no_role_tagged_evidence(self):
        html = render.render(TRACE, verdict_with(NO_ROLE_EVIDENCE))
        self.assertNotIn("Why it existed", html)
        self.assertNotIn("arc-section", html)

    def test_arc_appears_before_the_evidence_and_history_cards(self):
        html = render.render(TRACE, verdict_with(BOTH_ROLES_EVIDENCE))
        # "History:" (with the colon), not "History" alone, since the bare
        # word also appears inside this module's own CSS comments, which
        # render earlier in the document than any card ever could.
        self.assertLess(html.index("arc-section"), html.index("Evidence"))
        self.assertLess(html.index("arc-section"), html.index("History:"))

    def test_verdict_block_still_renders_first(self):
        html = render.render(TRACE, verdict_with(BOTH_ROLES_EVIDENCE))
        self.assertLess(html.index('class="verdict"'), html.index("arc-section"))
        # Nothing at all precedes the verdict block inside <main>.
        main_start = html.index("<main>")
        verdict_start = html.index('class="verdict"')
        between = html[main_start:verdict_start]
        self.assertNotIn("arc-section", between)
        self.assertNotIn('class="risk"', between)
        self.assertNotIn('class="stats"', between)


class TestIsolationFigures(unittest.TestCase):
    def test_zero_guard_count_renders_as_zero_not_omitted(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "commit", "ref": "c771002", "role": "reference",
             "note": "a comment still mentions this"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertIn("Current isolation", html)
        self.assertIn('<span class="stat-num">0</span>', html)
        self.assertIn('<span class="stat-num">1</span>', html)

    def test_omitted_entirely_when_no_role_tagged_evidence(self):
        html = render.render(TRACE, verdict_with(NO_ROLE_EVIDENCE))
        self.assertNotIn("Current isolation", html)
        self.assertNotIn('class="stats"', html)

    def test_counts_multiple_items_of_the_same_role(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "test", "ref": "payment_test.py:10", "role": "guard", "note": "one"},
            {"type": "test", "ref": "payment_test.py:20", "role": "guard", "note": "two"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertIn('<span class="stat-num">2</span>', html)
        self.assertIn('<span class="stat-num">0</span>', html)

    def test_a_single_guard_item_with_an_explicit_zero_count_still_renders(self):
        # An agent that searched for guarding tests and found none can
        # record that as one evidence item carrying its own "count": 0,
        # rather than needing zero guard items to say so. The block must
        # still render (one role-tagged item is present), and the figure
        # must show the explicit 0, not the item count of 1.
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "test", "ref": "grep -r target tests/", "role": "guard",
             "count": 0, "note": "no matches"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertIn("Current isolation", html)
        self.assertIn('<span class="stat-num">0</span>', html)


class TestRiskBlock(unittest.TestCase):
    def test_renders_near_the_verdict_using_the_warning_treatment(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "branch", "ref": "feature/still-calls-it", "role": "risk",
             "note": "will fail to compile if merged forward"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertIn("Residual risk", html)
        self.assertIn('class="risk"', html)
        self.assertIn("feature/still-calls-it", html)
        # Reuses the existing warning colours, not a new palette entry.
        self.assertIn("var(--warn-fg)", html)
        self.assertIn("var(--warn-bg)", html)
        # Near the verdict: appears before the History and Notes sections.
        self.assertLess(html.index('class="risk"'), html.index("History:"))
        self.assertLess(html.index('class="risk"'), html.index("Notes"))

    def test_renders_multiple_risk_items(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "branch", "ref": "feature/one", "role": "risk", "note": "calls it"},
            {"type": "branch", "ref": "feature/two", "role": "risk", "note": "also calls it"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertIn("feature/one", html)
        self.assertIn("feature/two", html)

    def test_absent_when_no_risk_evidence(self):
        html = render.render(TRACE, verdict_with(NO_ROLE_EVIDENCE))
        self.assertNotIn("Residual risk", html)
        self.assertNotIn('class="risk"', html)


class TestRoleStringsLocalizeToKorean(unittest.TestCase):
    def test_arc_isolation_and_risk_are_korean(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "role": "introduced", "note": "2023"},
            {"type": "commit", "ref": "b91c440", "role": "superseded", "note": "2026"},
            {"type": "commit", "ref": "c771002", "role": "reference", "note": "댓글 언급"},
            {"type": "branch", "ref": "feature/still-calls-it", "role": "risk",
             "note": "머지되면 빌드가 깨짐"},
        ]
        html = render.render(TRACE, verdict_with(evidence), lang="ko")
        self.assertIn("존재했던 이유", html)
        self.assertIn("도입", html)
        self.assertIn("대체됨", html)
        self.assertIn("현재 고립도", html)
        self.assertIn("잔존 위험", html)
        self.assertNotIn("Why it existed", html)
        self.assertNotIn("Current isolation", html)
        self.assertNotIn("Residual risk", html)
        # Data untouched by language.
        self.assertIn("댓글 언급", html)
        self.assertIn("머지되면 빌드가 깨짐", html)


class TestRoleTaggedNoteIsEscaped(unittest.TestCase):
    def test_injection_in_an_introduced_note_is_escaped(self):
        evidence = json.loads(json.dumps(BOTH_ROLES_EVIDENCE))
        evidence[0]["note"] = "<script>alert(1)</script> added in 2023"
        html = render.render(TRACE, verdict_with(evidence))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_injection_in_a_risk_note_is_escaped(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "branch", "ref": "feature/xss", "role": "risk",
             "note": "<img src=x onerror=alert(1)> will fail to compile"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertIn("&lt;img", html)

    def test_injection_in_a_reference_ref_is_escaped(self):
        evidence = [
            {"type": "commit", "ref": "a3f8c21", "note": "x"},
            {"type": "commit", "ref": "<b>c771002</b>", "role": "reference", "note": "n"},
        ]
        html = render.render(TRACE, verdict_with(evidence))
        self.assertNotIn("<b>c771002</b>", html)
        self.assertIn("&lt;b&gt;c771002&lt;/b&gt;", html)


if __name__ == "__main__":
    unittest.main()
