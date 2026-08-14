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

    def test_cap_is_disclosed(self):
        out = artifacts.scan_checklist(_scan_data(candidate_cap_reached=True))
        self.assertIn("200", out)

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


if __name__ == "__main__":
    unittest.main()
