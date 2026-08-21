"""Regression tests for v02 work item 2: needle quality and pickaxe scoping.

`trace._needles` used to take the first five tokens off the target lines
with no quality filter, and every needle ran repo-wide (`gitq.pickaxe`
called with no `path`). Common tokens (module names, ubiquitous
identifiers, language keywords) dragged in hundreds of unrelated commits.

This file pins three things:

1. `_rank_needles`/`_select_needles` drop stopwords, prefer longer and
   identifier-shaped tokens, verify rarity against the current tree with
   `gitq.grep_match_file_count`, and fall back to the old unranked
   behavior (rather than zero needles) when every token on the target
   lines is a stopword.
2. The synthetic `build_needle_junk_probe` fixture: a common,
   identifier-shaped token that out-ranks a rarer one by shape alone, but
   is deliberately planted across 20 unrelated commits. The real
   introducing commit must survive; the 20 unrelated commits must not.
3. `gitq.ALLOWED` gained `grep` (needed for the rarity check), and the
   guard around it still refuses `--open-files-in-pager` (see
   test_gitq.py::TestGrepAllowed for the direct guard tests).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import gitq
import trace as tracer


class TestRankNeedles(unittest.TestCase):
    """Pure logic, no git needed: ranking order given a token list."""

    def test_prefers_identifier_shaped_and_longer_tokens(self):
        ranked = tracer._rank_needles(["fix", "order_total_with_vat", "word"])
        self.assertEqual(ranked[0], "order_total_with_vat")

    def test_ties_keep_first_seen_order(self):
        # "alpha" and "bravo" tie on length and neither looks like an
        # identifier; a stable sort must not shuffle them.
        ranked = tracer._rank_needles(["alpha", "bravo"])
        self.assertEqual(ranked, ["alpha", "bravo"])

    def test_dotted_token_ranks_above_a_longer_plain_word(self):
        ranked = tracer._rank_needles(["something", "a.b"])
        self.assertEqual(ranked[0], "a.b")


class TestSelectNeedlesStopwordsAndFallback(unittest.TestCase):
    def _repo_with_line(self, line_text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "r"
        repo.mkdir()
        make_fixture_repo._git(repo, "init", "-q", "-b", "main")
        target = repo / "a.py"
        target.write_text("x = 1\n" + line_text + "\n")
        make_fixture_repo._commit(repo, "feat: add a", "2020-01-01T00:00:00")
        return str(repo)

    def test_stopword_is_dropped(self):
        repo = self._repo_with_line("    return order_total_with_vat")
        path_needles, repo_needles, notes, skipped = tracer._select_needles(repo, "a.py", 2, 2)
        self.assertFalse(skipped)
        self.assertNotIn("return", [n.lower() for n in path_needles])
        self.assertIn("order_total_with_vat", path_needles)
        # Nothing was stopworded away entirely, so no fallback note fires.
        self.assertFalse(any("fallback" in n or "stopword" in n for n in notes))

    def test_rare_identifier_is_preferred_over_a_stopword(self):
        repo = self._repo_with_line("    return order_total_with_vat")
        path_needles, _, _, _ = tracer._select_needles(repo, "a.py", 2, 2)
        self.assertEqual(path_needles[0], "order_total_with_vat")

    def test_fallback_when_every_token_is_a_stopword(self):
        # "return" and "true" are both in _STOPWORDS; nothing survives.
        repo = self._repo_with_line("    return true")
        path_needles, repo_needles, notes, skipped = tracer._select_needles(repo, "a.py", 2, 2)
        self.assertFalse(skipped)
        # Old behavior: needles are still produced, not an empty list.
        self.assertTrue(path_needles)
        self.assertIn("return", [n.lower() for n in path_needles])
        self.assertTrue(
            any("stopword" in n for n in notes),
            "notes must disclose the stopword fallback, got: {}".format(notes))


class TestNeedleJunkReduction(unittest.TestCase):
    """build_needle_junk_probe: a common, shape-preferred token planted
    across 20 unrelated commits must not flood introduction_candidates,
    while the real introducing commit still must.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_needle_junk_probe(self.tmp.name)

    def test_premise_common_token_alone_would_flood_repo_wide_pickaxe(self):
        # This is what the *old* code did: every needle ran repo-wide with
        # no rarity check. Pin that the common token really would have
        # pulled in a large number of commits if used unfiltered, so the
        # test below (asserting it is now excluded) is not vacuous.
        hits = gitq.pickaxe(self.info["repo"], self.info["common_token"])
        self.assertGreaterEqual(len(hits), 20)

    def test_the_real_commit_is_found(self):
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"])
        shas = {c["sha"] for c in result["introduction_candidates"]}
        self.assertIn(self.info["real_sha"], shas)

    def test_the_twenty_unrelated_commits_are_absent(self):
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"])
        shas = {c["sha"] for c in result["introduction_candidates"]}
        junk_present = [j for j in self.info["junk_shas"] if j in shas]
        self.assertEqual(junk_present, [],
                          "the common-token needle must not surface the "
                          "unrelated commits planted for it")

    def test_candidate_count_stays_small(self):
        # Not "exactly 1" (that would overfit to this fixture's exact
        # shape); just far below "real commit plus all 20 unrelated ones".
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"])
        self.assertLess(len(result["introduction_candidates"]), 5)

    def test_notes_disclose_the_common_token_was_deprioritized(self):
        result = tracer.trace(self.info["repo"], self.info["path"],
                               self.info["line"], self.info["line"])
        self.assertTrue(
            any(self.info["common_token"] in n for n in result["notes"]),
            "notes must name the deprioritized common token, got: {}".format(
                result["notes"]))


if __name__ == "__main__":
    unittest.main()
