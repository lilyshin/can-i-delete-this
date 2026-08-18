import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts


def _scan_data(candidates=None, **limits):
    base = {
        "files_scanned": 416, "files_skipped_unsupported": 1294,
        "files_skipped_vendored": 0, "files_skipped_generated": 0,
        "min_lines": 3, "max_candidates": 200,
        "candidate_cap_reached": False,
    }
    base.update(limits)
    return {
        "target": {"repo": "/tmp/r", "path": "src/billing"},
        "candidates": candidates if candidates is not None else [_candidate()],
        "limits": base,
        "notes": ["block comments (/* ... */) are not detected; only line comments"],
    }


def _candidate(**over):
    c = {
        "path": "src/billing/retry.py", "start": 88, "end": 92,
        "lines": 5, "code_lines": 4,
        "commented_out_by": {
            "sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
            "subject": "hotfix: disable retry during outage",
            "body": "Gateway kept returning 502. Restore after #3391.",
            "body_truncated": False,
            "author": "Chunsik", "author_email": "chunsik@example.com",
            "date": "2021-06-14T09:12:00+09:00", "age_days": 1886,
            "files_changed": 1, "hints": [],
        },
        "touched_by_commits": 1,
        "look_first": True,
    }
    c.update(over)
    return c


class TestChecklistShape(unittest.TestCase):

    def test_literal_checkbox_syntax(self):
        """0.2.2에서 이스케이프로 만든 체크박스가 깨진 채 출시됐다."""
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("- [ ] ", out)

    def test_target_and_lines_are_shown(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("src/billing/retry.py:88-92", out)

    def test_commit_facts_are_shown(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("1a2b3c4", out)
        self.assertIn("hotfix: disable retry during outage", out)
        self.assertIn("Restore after #3391", out)

    def test_age_is_shown(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("1886", out)

    def test_look_first_is_marked(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("**", out.split("- [ ] ")[1][:40])

    def test_scan_scope_is_disclosed(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("416", out)
        self.assertIn("1294", out)

    def test_scope_counts_too_large_and_missing_at_head(self):
        """scan.py도 이 두 사유로 파일을 건너뛴다; 체크리스트가 빠뜨리면 스캔 범위를
        실제보다 적게 보고하게 된다.

        숫자만 찾으면 안 된다: 앞선 `assertIn("2", out)`/`assertIn("3", out)`은
        출력 어딘가의 1294, 1a2b3c4, #3391 때문에 우연히 통과했다."""
        out = artifacts.scan_checklist(_scan_data(
            files_skipped_too_large=2, files_missing_at_head=3))
        self.assertIn("2 too large to read", out)
        self.assertIn("3 missing at HEAD", out)
        # total = 416 + 1294 + 0(vendored) + 0(generated) + 2(too_large) + 3(missing) = 1715
        self.assertIn("1715", out)

    def test_scope_counts_files_the_cap_left_unexamined(self):
        """상한에 걸려 열지도 않은 파일까지 세야 공개하는 총계가 '그 경로 아래
        추적 중인 파일 수'가 된다. 세지 않으면 총계가 상한 위치에 따라 달라진다."""
        out = artifacts.scan_checklist(_scan_data(
            candidate_cap_reached=True, files_not_reached=24))
        self.assertIn("24 never examined after the candidate cap", out)
        # total = 416 + 1294 + 24 = 1734
        self.assertIn("1734", out)

    def test_scope_total_is_unchanged_for_a_scan_without_the_new_key(self):
        """예전 스캔 JSON에는 files_not_reached가 없다. 없으면 0으로 읽고 총계는
        그대로여야 한다."""
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("1710", out)

    def test_cap_is_disclosed(self):
        out = artifacts.scan_checklist(_scan_data(candidate_cap_reached=True))
        self.assertIn("200", out)

    def test_zero_cap_does_not_claim_nothing_is_there(self):
        """--max-candidates 0은 '없다'가 아니라 '보고하지 않았다'이다. 아무것도
        보지 않은 스캔을 두고 아래에 블록이 없다고 말하면 거짓이다."""
        out = artifacts.scan_checklist(_scan_data(
            candidates=[], candidate_cap_reached=True, max_candidates=0))
        self.assertNotIn("No commented-out code blocks found", out)
        self.assertIn("the scan stopped at the candidate cap", out)
        self.assertIn("Candidate cap of 0 was reached", out)

    def test_zero_cap_wording_exists_in_korean_too(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[], candidate_cap_reached=True, max_candidates=0),
            lang="ko")
        self.assertIn("후보 상한에서", out)
        self.assertNotIn("주석 처리된 코드 블록이 없습니다", out)

    def test_commit_hints_are_shown_when_git_supplied_them(self):
        """blame이 준 것은 그 줄들을 가진 가장 오래된 커밋이지, 반드시 주석 처리한
        커밋은 아니다. scan.py가 이미 읽어둔 hints가 그 의심을 같은 자리에서
        말해준다."""
        commit = _candidate()["commented_out_by"]
        commit["hints"] = ["wide and shallow: 40 files, 1.2 lines changed "
                            "per file on average"]
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(commented_out_by=commit)]))
        self.assertIn("wide and shallow: 40 files", out)
        self.assertEqual(len([l for l in out.splitlines()
                              if "wide and shallow" in l]), 1)

    def test_no_hint_line_when_there_are_no_hints(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertNotIn("about that commit", out)

    def test_no_grade_words(self):
        out = artifacts.scan_checklist(_scan_data()).lower()
        for word in ("safe to delete", "do not delete", "danger", "conditional"):
            self.assertNotIn(word, out)

    def test_check_command_is_offered(self):
        out = artifacts.scan_checklist(_scan_data())
        self.assertIn("/can-i-delete-this:check", out)

    def test_empty_result_says_so_with_its_scope(self):
        """찾은 것이 없다와 안 찾았다는 다른 사실이다."""
        out = artifacts.scan_checklist(_scan_data(candidates=[]))
        self.assertIn("416", out)
        self.assertNotIn("- [ ] ", out)

    def test_missing_commit_facts_do_not_crash(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(commented_out_by=None, touched_by_commits=0,
                                    look_first=False)]))
        self.assertIn("src/billing/retry.py:88-92", out)
        # a candidate with no commit facts must render without inventing one
        self.assertNotIn("1a2b3c4", out)
        self.assertNotIn("hotfix: disable retry during outage", out)
        self.assertNotIn("Gateway kept returning 502", out)

    def test_touched_by_multiple_commits_is_shown(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(touched_by_commits=2)]))
        self.assertIn("2 commits touched these lines", out)

    def test_excerpt_is_rendered_with_pipe_prefix(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt=["for attempt in range(3):",
                                             "gateway.charge(order)"])]))
        self.assertIn("      | for attempt in range(3):", out)
        self.assertIn("      | gateway.charge(order)", out)

    def test_excerpt_and_body_quote_are_visually_distinct(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt=["for attempt in range(3):"])]))
        self.assertIn("      | for attempt in range(3):", out)
        self.assertIn("      > Gateway kept returning 502", out)

    def test_no_excerpt_key_means_no_excerpt_line(self):
        c = _candidate()
        c.pop("excerpt", None)
        out = artifacts.scan_checklist(_scan_data(candidates=[c]))
        self.assertNotIn("      | ", out)

    def test_empty_excerpt_list_means_no_excerpt_line(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt=[])]))
        self.assertNotIn("      | ", out)

    def test_malformed_excerpt_field_degrades_rather_than_raises(self):
        """The scan JSON is a file a user could hand-edit; a string instead
        of a list, or a list holding a non-string, must not crash the
        checklist renderer."""
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt="not a list")]))
        self.assertNotIn("      | ", out)

        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt=[42, None, "  ", "real line"])]))
        self.assertIn("      | real line", out)
        self.assertNotIn("      | 42", out)

    def test_truncated_body_is_marked(self):
        commit = _candidate()["commented_out_by"]
        commit["body_truncated"] = True
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(commented_out_by=commit)]))
        self.assertIn("git show", out)


class TestKorean(unittest.TestCase):

    def test_korean_chrome_and_untranslated_data(self):
        out = artifacts.scan_checklist(_scan_data(), lang="ko")
        self.assertIn("- [ ] ", out)
        self.assertIn("src/billing/retry.py:88-92", out)
        self.assertIn("hotfix: disable retry during outage", out)
        self.assertNotIn("Scan scope", out)

    def test_unknown_lang_falls_back_to_english(self):
        out = artifacts.scan_checklist(_scan_data(), lang="fr")
        self.assertIn("- [ ] ", out)

    def test_excerpt_text_is_not_translated_in_korean(self):
        """발췌는 파일에서 온 데이터이므로 ko 렌더링에서도 그대로 나와야 한다."""
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt=["for attempt in range(3):"])]),
            lang="ko")
        self.assertIn("      | for attempt in range(3):", out)

    def test_excerpt_text_is_not_translated_in_english(self):
        out = artifacts.scan_checklist(_scan_data(
            candidates=[_candidate(excerpt=["for attempt in range(3):"])]),
            lang="en")
        self.assertIn("      | for attempt in range(3):", out)


if __name__ == "__main__":
    unittest.main()
