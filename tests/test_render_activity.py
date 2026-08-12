"""render.py's activity facts (v0.4.0): when the target lines (or, failing
that, the file) were last touched, how many commits touched the file in
the last year, and its main authors -- rendered compactly inside the
History card, since recency/ownership is the strongest deterministic
"is this dead" signal the tool can offer.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import render

BASE_TRACE = {
    "target": {"path": "svc.py", "start": 1, "end": 1},
    "blame_candidates": [], "introduction_candidates": [], "revert_chain": [],
    "co_changed": [], "notes": [], "limits": {},
}

VERDICT = {
    "grade": "unknown",
    "summary": "test",
    "evidence": [],
    "conditions": [],
    "artifact": {"kind": "question", "content": "x"},
}


def _trace_with_activity(activity):
    data = json.loads(json.dumps(BASE_TRACE))
    data["activity"] = activity
    return data


class TestActivityFactsRender(unittest.TestCase):
    def setUp(self):
        self.activity = {
            "last_touch": {"sha": "a3f8c21" + "0" * 33,
                            "date": "2024-03-02T00:00:00+00:00", "scope": "lines"},
            "commits_last_year": 5,
            "top_authors": [{"name": "Alice", "count": 3}, {"name": "Bob", "count": 2}],
        }
        self.html = render.render(_trace_with_activity(self.activity), VERDICT)

    def test_lives_inside_the_history_card(self):
        history_pos = self.html.index("History: blame vs. the real introduction")
        activity_pos = self.html.index('class="activity"')
        timeline_pos = self.html.index('class="timeline"')
        self.assertLess(history_pos, activity_pos)
        self.assertLess(activity_pos, timeline_pos)

    def test_last_touch_lines_scope_is_labeled_as_lines(self):
        self.assertIn("Target lines last touched 2024-03-02 (a3f8c21)", self.html)

    def test_commits_last_year_count_shown(self):
        self.assertIn("5 commit(s) to this file in the last year", self.html)

    def test_main_authors_shown_with_counts(self):
        self.assertIn("Main authors: Alice (3), Bob (2)", self.html)


class TestLastTouchFileScopeIsLabeledDifferently(unittest.TestCase):
    def test_file_scope_says_so_rather_than_claiming_line_precision(self):
        activity = {
            "last_touch": {"sha": "b" * 40, "date": "2020-01-01T00:00:00+00:00",
                            "scope": "file"},
            "commits_last_year": 0,
            "top_authors": [],
        }
        html = render.render(_trace_with_activity(activity), VERDICT)
        self.assertIn("File last touched 2020-01-01", html)
        self.assertIn("target-line history was unavailable", html)
        self.assertNotIn("Target lines last touched", html)


class TestActivityDegradesPerFact(unittest.TestCase):
    def test_missing_last_touch_omits_only_that_fact(self):
        html = render.render(_trace_with_activity({
            "last_touch": None, "commits_last_year": 2, "top_authors": [],
        }), VERDICT)
        self.assertNotIn("last touched", html)
        self.assertIn("2 commit(s) to this file in the last year", html)

    def test_zero_commits_last_year_still_renders_the_fact(self):
        # 0 is falsy in Python but a real, informative answer here ("this
        # file has had no activity in a year" is exactly the dead-code
        # signal the feature exists to surface), so it must not be treated
        # like a missing value.
        html = render.render(_trace_with_activity({
            "last_touch": None, "commits_last_year": 0, "top_authors": [],
        }), VERDICT)
        self.assertIn("0 commit(s) to this file in the last year", html)

    def test_no_authors_omits_only_that_fact(self):
        html = render.render(_trace_with_activity({
            "last_touch": None, "commits_last_year": None, "top_authors": [],
        }), VERDICT)
        self.assertNotIn("Main authors", html)

    def test_every_fact_missing_renders_no_activity_list_at_all(self):
        html = render.render(_trace_with_activity({
            "last_touch": None, "commits_last_year": None, "top_authors": [],
        }), VERDICT)
        self.assertNotIn('class="activity"', html)


class TestActivityAbsentKeyIsBackwardCompatible(unittest.TestCase):
    def test_no_activity_key_at_all_renders_nothing_for_it(self):
        html = render.render(BASE_TRACE, VERDICT)
        self.assertNotIn('class="activity"', html)


class TestActivityEscaping(unittest.TestCase):
    def test_author_name_is_escaped(self):
        activity = {
            "last_touch": None, "commits_last_year": None,
            "top_authors": [{"name": "<script>alert(1)</script>", "count": 1}],
        }
        html = render.render(_trace_with_activity(activity), VERDICT)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestActivityLocalization(unittest.TestCase):
    def setUp(self):
        self.activity = {
            "last_touch": {"sha": "a3f8c21" + "0" * 33,
                            "date": "2024-03-02T00:00:00+00:00", "scope": "lines"},
            "commits_last_year": 5,
            "top_authors": [{"name": "Alice", "count": 3}],
        }

    def test_facts_are_korean(self):
        html = render.render(_trace_with_activity(self.activity), VERDICT, lang="ko")
        self.assertIn("대상 줄 최근 수정: 2024-03-02", html)
        self.assertIn("최근 1년간 이 파일에 커밋 5개", html)
        self.assertIn("주요 작성자: Alice (3)", html)
        self.assertNotIn("Target lines last touched", html)


if __name__ == "__main__":
    unittest.main()
