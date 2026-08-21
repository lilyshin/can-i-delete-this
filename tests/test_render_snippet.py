"""render.py's code-snippet block (v0.4.0): the target lines plus a few
lines of context, rendered directly under the verdict block so a reader
can see what is being judged without opening an editor.

Covers: available rendering with line numbers and a marked target line,
each of the four degraded cases (missing-at-head, out-of-range, binary,
irregular-line-break) rendering a short explanation instead of an empty
box or a crash,
localization, backward compatibility with a trace.json that predates the
`snippet` key, and escaping of arbitrary file content -- the highest-risk
injection surface on the page, since unlike a commit subject it is
attacker-shaped by construction (a real source file can contain anything).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import render

BASE_TRACE = {
    "target": {"path": "payment.py", "start": 3, "end": 3},
    "blame_candidates": [], "introduction_candidates": [], "revert_chain": [],
    "co_changed": [], "notes": [], "limits": {},
}

VERDICT = {
    "grade": "danger",
    "summary": "test",
    "evidence": [{"type": "commit", "ref": "a3f8c21"}],
    "conditions": [],
    "artifact": {"kind": "keep-comment", "content": "x"},
}


def _trace_with_snippet(snippet):
    data = json.loads(json.dumps(BASE_TRACE))
    data["snippet"] = snippet
    return data


class TestSnippetAvailable(unittest.TestCase):
    def setUp(self):
        self.snippet = {
            "available": True, "start_line": 1, "end_line": 4,
            "target_start": 3, "target_end": 3,
            "lines": [
                "def charge(order):",
                "    if order.already_charged:",
                '        return {"status": "duplicate"}',
                "    order.mark_processed()",
            ],
        }
        self.html = render.render(_trace_with_snippet(self.snippet), VERDICT)

    def test_appears_directly_under_the_verdict_block(self):
        verdict_end = self.html.index("</div>", self.html.index('<div class="verdict">'))
        snippet_pos = self.html.index('<div class="card snippet-card">')
        next_section = self.html.index("Evidence", snippet_pos)
        self.assertLess(verdict_end, snippet_pos)
        self.assertLess(snippet_pos, next_section)

    def test_all_context_lines_render_with_numbers(self):
        for n in range(1, 5):
            self.assertIn('<span class="snippet-num">{}</span>'.format(n), self.html)
        self.assertIn("def charge(order):", self.html)
        self.assertIn("order.mark_processed()", self.html)

    def test_target_line_is_marked_and_others_are_not(self):
        self.assertIn('<div class="snippet-row target">', self.html)
        # Exactly one row carries the "target" class for this single-line target.
        self.assertEqual(self.html.count('class="snippet-row target"'), 1)
        self.assertEqual(self.html.count('class="snippet-row"'), 3)

    def test_content_is_escaped(self):
        data = _trace_with_snippet({
            **self.snippet,
            "lines": ["</pre><script>alert(1)</script>"] + self.snippet["lines"][1:],
        })
        html = render.render(data, VERDICT)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;/pre&gt;&lt;script&gt;", html)


class TestSnippetDegradedCases(unittest.TestCase):
    def test_missing_at_head_shows_a_short_explanation(self):
        html = render.render(
            _trace_with_snippet({"available": False, "reason": "missing-at-head"}),
            VERDICT)
        self.assertIn("no longer exists at", html)
        self.assertNotIn('<div class="snippet-row', html)

    def test_out_of_range_shows_a_short_explanation(self):
        html = render.render(
            _trace_with_snippet({"available": False, "reason": "out-of-range"}),
            VERDICT)
        self.assertIn("past the", html)
        self.assertNotIn('<div class="snippet-row', html)

    def test_binary_shows_a_short_explanation(self):
        html = render.render(
            _trace_with_snippet({"available": False, "reason": "binary"}),
            VERDICT)
        self.assertIn("binary", html)
        self.assertNotIn('<div class="snippet-row', html)

    def test_irregular_line_break_shows_a_short_explanation(self):
        html = render.render(
            _trace_with_snippet({"available": False, "reason": "irregular-line-break"}),
            VERDICT)
        self.assertIn("unreliable", html)
        self.assertNotIn('<div class="snippet-row', html)

    def test_unrecognized_reason_falls_back_to_generic_text_not_a_raw_key(self):
        html = render.render(
            _trace_with_snippet({"available": False, "reason": "some-future-reason"}),
            VERDICT)
        self.assertIn('class="snippet-unavailable"', html)
        self.assertNotIn("snippet.unavailable.some-future-reason", html)

    def test_degraded_case_never_renders_an_empty_box(self):
        html = render.render(
            _trace_with_snippet({"available": False, "reason": "missing-at-head"}),
            VERDICT)
        self.assertIn('<p class="snippet-unavailable">', html)


class TestSnippetAbsentKeyIsBackwardCompatible(unittest.TestCase):
    def test_no_snippet_key_at_all_renders_nothing_for_it(self):
        # An older trace.json that predates this feature has no "snippet"
        # key; the block must simply not appear, not error or show an
        # "unavailable" message (which would be misleading -- nothing was
        # ever attempted).
        html = render.render(BASE_TRACE, VERDICT)
        self.assertNotIn('<div class="card snippet-card">', html)
        self.assertNotIn('class="snippet-unavailable"', html)


class TestSnippetLocalization(unittest.TestCase):
    def setUp(self):
        self.snippet = {
            "available": True, "start_line": 1, "end_line": 2,
            "target_start": 1, "target_end": 1,
            "lines": ["a = 1", "b = 2"],
        }

    def test_header_is_korean(self):
        html = render.render(_trace_with_snippet(self.snippet), VERDICT, lang="ko")
        self.assertIn("<strong>코드</strong>", html)
        self.assertNotIn(">Code<", html)

    def test_degraded_messages_are_korean(self):
        for reason, needle in [
            ("missing-at-head", "HEAD에 더 이상 없어서"),
            ("out-of-range", "파일 끝을 넘어섰습니다"),
            ("binary", "바이너리라"),
            ("irregular-line-break", "줄 번호를 믿을 수 없게"),
        ]:
            with self.subTest(reason=reason):
                html = render.render(
                    _trace_with_snippet({"available": False, "reason": reason}),
                    VERDICT, lang="ko")
                self.assertIn(needle, html)

    def test_source_code_itself_is_never_translated(self):
        html = render.render(_trace_with_snippet(self.snippet), VERDICT, lang="ko")
        self.assertIn("a = 1", html)
        self.assertIn("b = 2", html)


if __name__ == "__main__":
    unittest.main()
