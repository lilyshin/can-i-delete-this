"""trace.py's three report-facing additions (v0.4.0): the code snippet
under the verdict, the History card's recency/ownership facts, and the
reproduction commands at the bottom of the report. All three are computed
here, not in render.py, so render.py stays a renderer (see render.py's
module docstring) and an older trace.json that predates these keys still
renders (see test_render_snippet.py / test_render_activity.py /
test_render_repro.py for the render-side half of that contract).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import trace as tracer


class TestSnippetAvailable(unittest.TestCase):
    """F1's target line 3 (`return {"status": "duplicate"}`) with a 4-line
    file, so the whole file is within context range on both sides.
    """

    def test_renders_with_context_and_marks_the_target_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        snippet = result["snippet"]
        self.assertTrue(snippet["available"])
        self.assertEqual(snippet["start_line"], 1)
        self.assertEqual(snippet["end_line"], 4)
        self.assertEqual(snippet["target_start"], 3)
        self.assertEqual(snippet["target_end"], 3)
        self.assertEqual(len(snippet["lines"]), 4)
        # Line 3 (index 2, since start_line is 1) is the target content.
        self.assertIn("duplicate", snippet["lines"][2])

    def test_context_is_bounded_to_a_handful_of_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_deep_history(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        snippet = result["snippet"]
        self.assertTrue(snippet["available"])
        # deep_history's file has many lines; the shown window must stay
        # small (a handful of lines each side), not the whole file, so the
        # block does not crowd the verdict it renders directly under.
        self.assertLessEqual(snippet["end_line"] - snippet["start_line"] + 1, 15)


class TestSnippetDegradesCleanly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_f1(self.tmp.name)

    def test_missing_path_at_head(self):
        snippet = tracer._compute_snippet(self.info["repo"], "no_such_file.py", 1, 1)
        self.assertFalse(snippet["available"])
        self.assertEqual(snippet["reason"], "missing-at-head")

    def test_line_range_past_end_of_file(self):
        snippet = tracer._compute_snippet(self.info["repo"], self.info["path"], 500, 501)
        self.assertFalse(snippet["available"])
        self.assertEqual(snippet["reason"], "out-of-range")

    def test_end_past_file_but_start_valid_is_clamped_not_refused(self):
        # payment.py has 4 lines; asking for 3:100 starts inside the file,
        # so showing what exists is more useful than refusing outright.
        snippet = tracer._compute_snippet(self.info["repo"], self.info["path"], 3, 100)
        self.assertTrue(snippet["available"])
        self.assertEqual(snippet["target_end"], 4)

    def test_binary_file(self):
        with tempfile.TemporaryDirectory() as tmp2:
            info = make_fixture_repo.build_binary_target(tmp2)
            snippet = tracer._compute_snippet(info["repo"], info["path"], info["line"], info["line"])
        self.assertFalse(snippet["available"])
        self.assertEqual(snippet["reason"], "binary")

    def test_undecodable_file_with_no_nul_byte_is_still_binary(self):
        # The gitq.run_git_bytes fix for the lone-CR finding moved the
        # NUL check to run on raw bytes before decoding is even
        # attempted (see trace.py's `_read_snippet_source`); this pins
        # that a decode failure with no NUL byte at all still reaches
        # "binary" through the separate `UnicodeDecodeError` branch, not
        # just through the NUL check `build_binary_target`'s content
        # happens to trip first.
        with tempfile.TemporaryDirectory() as tmp2:
            info = make_fixture_repo.build_undecodable_no_nul_target(tmp2)
            snippet = tracer._compute_snippet(info["repo"], info["path"], info["line"], info["line"])
        self.assertFalse(snippet["available"])
        self.assertEqual(snippet["reason"], "binary")

    def test_none_of_the_degraded_cases_raise_through_the_full_trace(self):
        # Full trace() must not crash even though its own target path is
        # perfectly fine; this pins that _compute_snippet's degraded
        # branches are only ever reached deliberately (direct calls above),
        # never as an accidental side effect of a normal trace() run.
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"])
        self.assertTrue(result["snippet"]["available"])


class TestActivityAgainstKnownFixture(unittest.TestCase):
    def test_facts_match_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_activity_probe(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        activity = result["activity"]

        self.assertEqual(activity["commits_last_year"], info["commits_last_year"])

        self.assertEqual(activity["last_touch"]["sha"], info["last_sha"])
        self.assertEqual(activity["last_touch"]["scope"], "lines")

        names = [a["name"] for a in activity["top_authors"]]
        counts = {a["name"]: a["count"] for a in activity["top_authors"]}
        self.assertEqual(names[0], info["top_author"])
        self.assertEqual(counts[info["top_author"]], info["top_author_count"])
        self.assertEqual(counts[info["second_author"]], info["second_author_count"])

    def test_falls_back_to_file_scope_when_line_history_has_nothing(self):
        # A synthetic empty line_history_shas list simulates the case
        # where the line-history search found nothing to report (not the
        # same as it raising -- that path is exercised by trace() itself
        # whenever gitq.line_history succeeds with zero hits, which is
        # legitimate: the file could have been touched by a commit that
        # rewrote lines around, but not through, the target range).
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            activity = tracer._compute_activity(info["repo"], info["path"], [], {})
        self.assertEqual(activity["last_touch"]["scope"], "file")
        self.assertIsNotNone(activity["last_touch"]["date"])


class TestReproductionCommandsMatchWhatRan(unittest.TestCase):
    def test_blame_pickaxe_and_line_history_commands_are_recorded_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        commands = result["commands"]
        kinds = [c["kind"] for c in commands]
        self.assertIn("blame", kinds)
        self.assertIn("pickaxe", kinds)
        self.assertIn("line-history", kinds)

        blame_cmd = next(c for c in commands if c["kind"] == "blame")
        self.assertEqual(blame_cmd["args"],
                          ["blame", "-w", "-C", "-C", "-C", "--porcelain",
                           "-L", "3,3", "--", "payment.py"])

        line_history_cmd = next(c for c in commands if c["kind"] == "line-history")
        self.assertEqual(line_history_cmd["args"],
                          ["log", "--format=%H", "-L", "3,3:payment.py",
                           "--max-count=5000"])

        for cmd in commands:
            if cmd["kind"] == "pickaxe":
                self.assertIn(cmd["scope"], ("path", "repo"))
                self.assertIn("-S", cmd["args"])
                self.assertIn(cmd["needle"], cmd["args"])

    def test_pickaxe_is_absent_entirely_when_no_needle_was_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_no_needle_target(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        kinds = [c["kind"] for c in result["commands"]]
        self.assertNotIn("pickaxe", kinds)
        # blame and line-history still ran and are still recorded.
        self.assertIn("blame", kinds)
        self.assertIn("line-history", kinds)

    def test_repo_path_is_recorded_for_reproduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        self.assertEqual(result["repo"], info["repo"])


if __name__ == "__main__":
    unittest.main()
