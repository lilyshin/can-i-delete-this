import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import render

TRACE = {
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

VERDICT = {
    "grade": "danger",
    "summary": "Guards against the #4127 double charge incident.",
    "evidence": [{"type": "commit", "ref": "a3f8c21", "note": "introduced during incident"}],
    "conditions": [],
    "artifact": {"kind": "keep-comment",
                 "content": "// KEEP: incident #4127. See payment_test.py:88."},
}


class TestRender(unittest.TestCase):
    def setUp(self):
        self.html = render.render(TRACE, VERDICT)

    def test_is_self_contained(self):
        for forbidden in ["http://", "https://cdn", "<link", "@import", "src=\"http"]:
            self.assertNotIn(forbidden, self.html)

    def test_supports_both_color_schemes(self):
        self.assertIn("prefers-color-scheme: dark", self.html)

    def test_shows_real_commit_and_marks_blame_as_wrong(self):
        self.assertIn("hotfix: prevent double charge (#4127)", self.html)
        self.assertIn("chore: apply formatter", self.html)
        self.assertIn("N1", self.html)

    def test_truncation_is_disclosed(self):
        self.assertIn("truncated", self.html.lower())

    def test_artifact_is_copyable(self):
        self.assertIn("navigator.clipboard", self.html)
        self.assertIn("KEEP: incident #4127", self.html)

    def test_escapes_html_in_subjects(self):
        data = json.loads(json.dumps(TRACE))
        data["introduction_candidates"][0]["subject"] = "fix: <script>alert(1)</script>"
        html = render.render(data, VERDICT)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_write_report_stays_out_of_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = render.write_report(TRACE, VERDICT, outdir=tmp)
            self.assertTrue(Path(path).is_file())
            self.assertTrue(path.startswith(tmp))

    def test_escapes_html_in_author_name_with_quotes(self):
        data = json.loads(json.dumps(TRACE))
        data["introduction_candidates"][0]["author"] = 'Kim "the closer" <b>'
        html = render.render(data, VERDICT)
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;", html)

    def test_escapes_ampersand_in_path(self):
        data = json.loads(json.dumps(TRACE))
        data["target"]["path"] = "billing & payment.py"
        html = render.render(data, VERDICT)
        self.assertNotIn("billing & payment.py", html)
        self.assertIn("billing &amp; payment.py", html)

    def test_escapes_notes_and_artifact_content(self):
        data = json.loads(json.dumps(TRACE))
        data["notes"] = ["<img src=x onerror=alert(1)>"]
        verdict = json.loads(json.dumps(VERDICT))
        verdict["artifact"]["content"] = "<script>evil()</script>"
        html = render.render(data, verdict)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertNotIn("<script>evil()</script>", html)
        self.assertIn("&lt;img", html)
        self.assertIn("&lt;script&gt;evil()", html)

    def test_discloses_candidate_cap_reached(self):
        data = json.loads(json.dumps(TRACE))
        data["limits"]["candidate_cap_reached"] = True
        data["limits"]["max_candidates"] = 200
        html = render.render(data, VERDICT)
        self.assertIn("200", html)
        self.assertIn("candidate", html.lower())

    def test_no_placeholder_text_leaks_through(self):
        for placeholder in ["TODO", "{{", "}}", "PLACEHOLDER", "%s"]:
            self.assertNotIn(placeholder, self.html)


if __name__ == "__main__":
    unittest.main()
