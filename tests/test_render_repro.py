"""render.py's reproduction-commands section (v0.4.0): a collapsed
<details> at the very bottom of the page listing the actual git commands
this trace ran, plus `git show` for whichever commit the verdict cites,
with a copy button reusing the existing clipboard mechanism.

The core property under test is honesty: every line shown must correspond
to a command trace.py actually recorded in `commands`, and a search that
did not run (an empty needle list, an unresolved citation) must not
produce a fabricated line.
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

COMMANDS = [
    {"kind": "blame", "args": ["blame", "-w", "-C", "-C", "-C", "--porcelain",
                                "-L", "3,3", "--", "payment.py"]},
    {"kind": "pickaxe", "scope": "path", "needle": "already_charged",
     "args": ["log", "--format=%H", "-S", "already_charged", "--max-count=5000",
              "--", "payment.py"]},
    {"kind": "line-history",
     "args": ["log", "--format=%H", "-L", "3,3:payment.py", "--max-count=5000"]},
]


def _trace(commands=COMMANDS, repo="/tmp/some-repo"):
    data = json.loads(json.dumps(BASE_TRACE))
    if commands is not None:
        data["commands"] = commands
    if repo is not None:
        data["repo"] = repo
    return data


def _trace_with_cited_candidate():
    data = _trace()
    data["introduction_candidates"] = [{
        "sha": "a3f8c21" + "0" * 33, "why": "pickaxe",
        "subject": "hotfix", "date": "2019-01-01T00:00:00+00:00",
        "author": "Kim", "author_email": "kim@example.com", "files_changed": 1,
    }]
    return data


class TestReproCommandsRender(unittest.TestCase):
    def setUp(self):
        self.verdict = {
            "grade": "danger", "summary": "test",
            "evidence": [{"type": "commit", "ref": "a3f8c21"}],
            "conditions": [], "artifact": {"kind": "keep-comment", "content": "x"},
        }
        self.html = render.render(_trace_with_cited_candidate(), self.verdict)

    def test_is_a_collapsed_details_at_the_very_bottom(self):
        self.assertIn('<details class="repro">', self.html)
        main_end = self.html.rindex("</main>")
        repro_pos = self.html.index('<details class="repro">')
        self.assertLess(repro_pos, main_end)
        # Nothing meaningful (another section/card) sits after it inside <main>.
        after = self.html[repro_pos:main_end]
        self.assertNotIn("<div class=\"section", after[len('<details class="repro">'):]
                          .split("</details>")[-1])

    def test_has_a_copy_button_reusing_the_existing_mechanism(self):
        self.assertIn('data-copy="repro-cmds"', self.html)
        self.assertIn('id="repro-cmds"', self.html)

    def test_shows_the_real_repo_path_file_and_line_range(self):
        self.assertIn("git -C /tmp/some-repo blame", self.html)
        self.assertIn("-L 3,3", self.html)
        self.assertIn("payment.py", self.html)

    def test_includes_blame_pickaxe_line_history_and_git_show(self):
        self.assertIn("blame -w -C -C -C --porcelain", self.html)
        self.assertIn("-S already_charged", self.html)
        self.assertIn("-L 3,3:payment.py", self.html)
        self.assertIn("show a3f8c21", self.html)


class TestReproOmitsWhatDidNotRun(unittest.TestCase):
    def test_no_pickaxe_line_when_none_was_recorded(self):
        commands = [c for c in COMMANDS if c["kind"] != "pickaxe"]
        html = render.render(_trace(commands=commands), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        })
        self.assertIn("blame", html)
        self.assertNotIn("-S already_charged", html)

    def test_no_git_show_line_when_nothing_was_cited(self):
        html = render.render(_trace(), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        })
        self.assertNotIn("git -C /tmp/some-repo show", html)

    def test_no_repro_block_at_all_when_commands_key_is_absent(self):
        # Older trace.json that predates this feature.
        html = render.render(_trace(commands=None), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        })
        self.assertNotIn('<details class="repro">', html)

    def test_no_repro_block_at_all_when_repo_key_is_absent(self):
        html = render.render(_trace(repo=None), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        })
        self.assertNotIn('<details class="repro">', html)


class TestReproShowsCitedCommitOnly(unittest.TestCase):
    def test_git_show_matches_the_commit_the_verdict_actually_cites(self):
        trace_data = _trace()
        trace_data["introduction_candidates"] = [{
            "sha": "d20124100000000000000000000000000000001", "why": "pickaxe",
            "subject": "hotfix", "date": "2019-01-01T00:00:00+00:00",
            "author": "Kim", "author_email": "kim@example.com", "files_changed": 1,
        }]
        verdict = {
            "grade": "danger", "summary": "s",
            "evidence": [{"type": "commit", "ref": "d201241"}],
            "conditions": [], "artifact": {"kind": "keep-comment", "content": "x"},
        }
        html = render.render(trace_data, verdict)
        self.assertIn(
            "git -C /tmp/some-repo show d20124100000000000000000000000000000001", html)


class TestReproEscapingAndLocalization(unittest.TestCase):
    def test_needle_and_path_are_shell_quoted_when_they_contain_spaces(self):
        # shlex.quote wraps a space-containing token in single quotes;
        # those quotes are themselves HTML-escaped like the rest of this
        # command text (see test_command_text_is_html_escaped), so the
        # raw HTML carries the escaped entity form. A browser (and a
        # `.textContent`-based copy, via the existing clipboard button)
        # both decode entities back to a literal `'`, so the text a user
        # actually sees or copies is the correctly single-quoted command.
        commands = [{"kind": "blame",
                     "args": ["blame", "-L", "1,1", "--", "weird file name.py"]}]
        html = render.render(_trace(commands=commands, repo="/path with space"), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        })
        self.assertIn("&#x27;weird file name.py&#x27;", html)
        self.assertIn("&#x27;/path with space&#x27;", html)

    def test_command_text_is_html_escaped(self):
        commands = [{"kind": "blame", "args": ["blame", "-L", "1,1", "--", "<a>.py"]}]
        html = render.render(_trace(commands=commands), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        })
        self.assertNotIn("<a>.py", html)
        self.assertIn("&lt;a&gt;.py", html)

    def test_header_and_copy_button_are_korean(self):
        html = render.render(_trace(), {
            "grade": "unknown", "summary": "s", "evidence": [], "conditions": [],
            "artifact": {"kind": "question", "content": "x"},
        }, lang="ko")
        self.assertIn("<summary>재현 명령어</summary>", html)
        self.assertIn(">복사<", html)


if __name__ == "__main__":
    unittest.main()
