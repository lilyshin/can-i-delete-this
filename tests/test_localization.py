"""Regression tests for the `--lang` localization option (v0.2.2).

render.py and artifacts.py used to hardcode their own English chrome (badge
labels, card headers, the dot legend, tag text, disclosures, the artifact
skeletons, the unresolved-citation message, the Grade:/Target: labels)
around whatever language the agent's own prose came out in, so a Korean
user got Korean analysis wrapped in English chrome. These tests pin the
fix:

- `lang` defaults to `"en"` on both `render()` and `skeleton()`, so every
  existing caller (and every existing test, which calls both with no
  `lang` argument) keeps producing exactly the text it produced before
  this option existed.
- an explicit `"en"` is identical to the default.
- an unknown lang value falls back to `"en"` rather than raising.
- `"ko"` translates the chrome this module writes while leaving data read
  from git or the verdict (shas, paths, commit subjects, author names,
  dates) untouched.
- the escaping this project already relies on (see test_render.py's own
  injection tests) still holds when the chrome around the escaped data is
  Korean instead of English.
- the collapsed-history `<summary>` count stays correct and escaped in
  both languages.
- the page's `<html lang="...">` attribute matches the language actually
  rendered.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts
import render


RENDER_TRACE = {
    "target": {"path": "payment.py", "start": 3, "end": 3},
    "blame_candidates": [{
        "sha": "e91b44f" + "0" * 33, "subject": "chore: apply formatter",
        "date": "2023-06-01T09:00:00+00:00", "author": "Bot",
        "noise": {"is_noise": True, "category": "N1", "confidence": 0.8,
                  "signals": ["diff is empty when whitespace is ignored"]},
    }],
    "introduction_candidates": [{
        "sha": "a3f8c21" + "0" * 33, "why": "pickaxe",
        "subject": "hotfix: prevent double charge (#4127)",
        "date": "2019-11-08T02:14:00+00:00", "author": "Kim",
        "author_email": "kim@example.com", "files_changed": 1,
    }],
    "revert_chain": [],
    "co_changed": [{"path": "payment_test.py", "sha": "a3f8c21" + "0" * 33}],
    "limits": {"max_commits": 5000, "since": "5 years ago", "truncated": True,
               "max_candidates": 200, "candidate_cap_reached": False},
    "notes": ["blame returned only noise commits; falling back to pickaxe"],
}

RENDER_VERDICT = {
    "grade": "danger",
    "summary": "Guards against the #4127 double charge incident.",
    "evidence": [{"type": "commit", "ref": "a3f8c21", "note": "introduced during incident"}],
    "conditions": [],
    "artifact": {"kind": "keep-comment",
                 "content": "// KEEP: incident #4127. See payment_test.py:88."},
}


class TestRenderLangDefaultAndFallback(unittest.TestCase):
    def test_default_and_explicit_en_are_identical(self):
        self.assertEqual(render.render(RENDER_TRACE, RENDER_VERDICT),
                          render.render(RENDER_TRACE, RENDER_VERDICT, lang="en"))

    def test_unknown_lang_falls_back_to_en_without_raising(self):
        try:
            html = render.render(RENDER_TRACE, RENDER_VERDICT, lang="fr")
        except Exception as exc:
            self.fail("an unknown lang value must fall back to en, not raise: "
                      "{}".format(exc))
        self.assertEqual(html, render.render(RENDER_TRACE, RENDER_VERDICT, lang="en"))

    def test_html_lang_attribute_matches_the_chosen_language(self):
        self.assertIn('<html lang="en">', render.render(RENDER_TRACE, RENDER_VERDICT))
        self.assertIn('<html lang="ko">',
                       render.render(RENDER_TRACE, RENDER_VERDICT, lang="ko"))

    def test_unknown_lang_renders_the_fallback_attribute_not_the_literal_value(self):
        html = render.render(RENDER_TRACE, RENDER_VERDICT, lang="fr")
        self.assertIn('<html lang="en">', html)
        self.assertNotIn('lang="fr"', html)


class TestRenderKoreanChrome(unittest.TestCase):
    def setUp(self):
        self.html = render.render(RENDER_TRACE, RENDER_VERDICT, lang="ko")

    def test_badge_is_korean_not_english(self):
        self.assertIn("삭제 금지", self.html)
        self.assertNotIn(">Do not delete<", self.html)

    def test_card_headers_are_korean(self):
        self.assertIn("근거", self.html)  # Evidence
        self.assertIn("조사 노트와 제한사항", self.html)  # Notes and limits
        self.assertIn("다음 행동", self.html)  # Next step (...)
        self.assertNotIn(">Evidence<", self.html)
        self.assertNotIn(">Notes and limits<", self.html)

    def test_legend_is_korean_and_short(self):
        self.assertIn('class="legend"', self.html)
        self.assertIn("검증이 실제 도입 커밋으로 지목한 커밋", self.html)
        self.assertIn("노이즈로 채점되어 인용되지 않은 커밋", self.html)
        self.assertIn("인용되지도 노이즈로도 채점되지 않은 후보", self.html)
        self.assertIn("revert/reapply 체인의 일부", self.html)

    def test_co_changed_label_is_korean(self):
        self.assertIn("도입 커밋에서 함께 변경된 파일", self.html)
        self.assertNotIn("Also touched in the introducing commit", self.html)

    def test_truncation_disclosure_is_korean(self):
        self.assertIn("히스토리 탐색이", self.html)
        self.assertNotIn("History walk was truncated", self.html)

    def test_data_is_untouched_by_language(self):
        # shas, paths, subjects, authors and dates come from the trace and
        # verdict, never from the string table, so they render unchanged
        # regardless of lang.
        for needle in ("a3f8c21", "payment.py", "payment_test.py",
                       "hotfix: prevent double charge (#4127)",
                       "chore: apply formatter", "Kim", "2019-11-08"):
            self.assertIn(needle, self.html)


class TestRenderInjectionStaysEscapedInKorean(unittest.TestCase):
    def test_combined_payload_is_escaped_in_a_ko_render(self):
        data = json.loads(json.dumps(RENDER_TRACE))
        data["introduction_candidates"][0]["subject"] = \
            "fix: <script>alert(1)</script> 한글 <b>bold</b>"
        data["introduction_candidates"][0]["author"] = 'Kim "the closer" <b>'
        data["target"]["path"] = "billing & <b>payment</b>.py"
        data["notes"] = ["<img src=x onerror=alert(1)> 노트"]
        verdict = json.loads(json.dumps(RENDER_VERDICT))
        verdict["artifact"]["content"] = "<script>evil()</script> 결과"

        html = render.render(data, verdict, lang="ko")

        for forbidden in ("<script>alert(1)</script>", "<b>bold</b>",
                          "<img src=x onerror=alert(1)>", "<script>evil()</script>",
                          "billing & <b>payment</b>.py"):
            self.assertNotIn(forbidden, html)
        for expected in ("&lt;script&gt;", "&lt;b&gt;bold&lt;/b&gt;", "&lt;img",
                          "billing &amp; &lt;b&gt;payment&lt;/b&gt;.py"):
            self.assertIn(expected, html)
        # The Korean text sitting right next to the injected payload must
        # still render: escaping and localization must not fight each other.
        self.assertIn("한글", html)
        self.assertIn("노트", html)
        self.assertIn("결과", html)


def _sha(prefix):
    return (prefix + "0" * 40)[:40]


def _long_trace_and_real_sha():
    real_sha = _sha("a1a1a1a")
    other_shas = [_sha("d{}d{}d".format(i, i)) for i in range(15)]
    trace = {
        "target": {"path": "big.py", "start": 10, "end": 10},
        "blame_candidates": [
            {"sha": real_sha, "subject": "fix: the real introduction",
             "date": "2019-01-01T00:00:00+00:00", "author": "Kim",
             "noise": {"is_noise": False, "category": "", "confidence": 0.0,
                       "signals": []}},
        ],
        "introduction_candidates": [
            {"sha": real_sha, "why": "blame", "subject": "fix: the real introduction",
             "date": "2019-01-01T00:00:00+00:00", "author": "Kim",
             "author_email": "kim@example.com", "files_changed": 1},
        ] + [
            {"sha": sha, "why": "pickaxe",
             "subject": "chore: unrelated commit {}".format(i),
             "date": "2020-0{}-01T00:00:00+00:00".format((i % 9) + 1),
             "author": "Someone", "author_email": "someone@example.com",
             "files_changed": 1}
            for i, sha in enumerate(other_shas)
        ],
        "revert_chain": [],
        "co_changed": [],
        "limits": {"max_commits": 5000, "since": None, "truncated": False,
                   "max_candidates": 200, "candidate_cap_reached": False},
        "notes": [],
    }
    return trace, real_sha


def _verdict_citing(real_sha):
    return {
        "grade": "conditional",
        "summary": "Looks load-bearing; verify before deleting.",
        "evidence": [{"type": "commit", "ref": real_sha[:7], "note": "the real fix"}],
        "conditions": [],
        "artifact": {"kind": "keep-comment", "content": "// KEEP: see above"},
    }


class TestHistoryCollapseSummaryLocalization(unittest.TestCase):
    def test_count_is_correct_and_escaped_in_english(self):
        trace_data, real_sha = _long_trace_and_real_sha()
        html = render.render(trace_data, _verdict_citing(real_sha), lang="en")
        self.assertIn("Other candidates from the search (15 commits)", html)

    def test_count_is_correct_and_escaped_in_korean(self):
        trace_data, real_sha = _long_trace_and_real_sha()
        html = render.render(trace_data, _verdict_citing(real_sha), lang="ko")
        self.assertIn("검색된 다른 후보 (15개 커밋)", html)


ARTIFACT_TRACE = {
    "target": {"path": "payment.py", "start": 3, "end": 3},
    "introduction_candidates": [{
        "sha": "a3f8c21" + "0" * 33, "subject": "hotfix: prevent double charge (#4127)",
        "date": "2019-11-08T02:14:00+00:00", "author": "Kim",
        "author_email": "kim@example.com", "why": "pickaxe",
    }],
    "co_changed": [{"path": "payment_test.py", "sha": "a3f8c21" + "0" * 33}],
    "blame_candidates": [], "revert_chain": [], "notes": [],
    "limits": {"truncated": False, "max_commits": 5000, "since": "5 years ago"},
}


class TestArtifactsLangDefaultAndFallback(unittest.TestCase):
    def test_default_and_explicit_en_are_identical(self):
        for grade in ("danger", "conditional", "safe", "unknown"):
            with self.subTest(grade=grade):
                self.assertEqual(
                    artifacts.skeleton(grade, ARTIFACT_TRACE),
                    artifacts.skeleton(grade, ARTIFACT_TRACE, lang="en"))

    def test_unknown_lang_falls_back_to_en_without_raising(self):
        for grade in ("danger", "conditional", "safe", "unknown"):
            with self.subTest(grade=grade):
                out = artifacts.skeleton(grade, ARTIFACT_TRACE, lang="fr")
                self.assertEqual(out, artifacts.skeleton(grade, ARTIFACT_TRACE, lang="en"))


class TestArtifactsKoreanSkeletons(unittest.TestCase):
    def test_danger_skeleton_with_a_guarding_test_is_korean(self):
        # ARTIFACT_TRACE's co_changed carries payment_test.py for the cited
        # commit, so this is the "with a guarding test" branch.
        out = artifacts.skeleton("danger", ARTIFACT_TRACE, lang="ko")
        self.assertIn("유지", out)
        self.assertIn("a3f8c21", out)
        self.assertIn("#4127", out)
        self.assertIn("payment_test.py", out)
        self.assertNotIn("KEEP", out)
        self.assertNotIn("Before deleting", out)

    def test_danger_skeleton_without_a_guarding_test_is_korean(self):
        trace = {**ARTIFACT_TRACE, "co_changed": []}
        out = artifacts.skeleton("danger", trace, lang="ko")
        self.assertIn("테스트가 없습니다", out)
        self.assertNotIn("no test guards this", out)

    def test_conditional_skeleton_is_a_korean_checklist(self):
        out = artifacts.skeleton("conditional", ARTIFACT_TRACE, lang="ko")
        self.assertIn("- [ ]", out)
        self.assertIn("payment.py", out)
        self.assertIn("a3f8c21", out)
        self.assertNotIn("Deletion checklist", out)

    def test_safe_skeleton_is_korean(self):
        out = artifacts.skeleton("safe", ARTIFACT_TRACE, lang="ko")
        self.assertIn("근거:", out)
        self.assertIn("a3f8c21", out)
        self.assertNotIn("Evidence:", out)

    def test_unknown_skeleton_names_who_to_ask_in_korean(self):
        out = artifacts.skeleton("unknown", ARTIFACT_TRACE, lang="ko")
        self.assertIn("Kim", out)
        self.assertIn("kim@example.com", out)
        self.assertIn("아시는 분", out)
        self.assertNotIn("Does anyone remember", out)

    def test_unresolved_citation_uses_korean_grade_and_target_labels(self):
        trace = {**ARTIFACT_TRACE, "introduction_candidates": []}
        out = artifacts.skeleton(
            "danger", trace,
            evidence=[{"type": "commit", "ref": "deadbee"}],
            lang="ko")
        self.assertIn("등급: danger", out)
        self.assertIn("대상: payment.py:3", out)
        self.assertNotIn("Grade:", out)
        self.assertNotIn("Target:", out)
        self.assertIn("deadbee", out)


if __name__ == "__main__":
    unittest.main()
