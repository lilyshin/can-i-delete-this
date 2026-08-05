import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import trace as tracer


class TestF1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.info = make_fixture_repo.build_f1(self.tmp.name)
        self.result = tracer.trace(
            self.info["repo"], self.info["path"],
            self.info["line"], self.info["line"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_blame_candidate_is_flagged_as_noise(self):
        blamed = self.result["blame_candidates"][0]
        self.assertTrue(blamed["sha"].startswith(self.info["noise_sha"][:7]))
        self.assertTrue(blamed["noise"]["is_noise"])
        self.assertEqual(blamed["noise"]["category"], "N1")

    def test_real_introducing_commit_is_top_candidate(self):
        top = self.result["introduction_candidates"][0]
        self.assertEqual(top["sha"], self.info["real_sha"])
        self.assertEqual(top["subject"], "hotfix: prevent double charge (#4127)")

    def test_formatter_commit_is_not_an_introduction_candidate(self):
        shas = [c["sha"] for c in self.result["introduction_candidates"]]
        self.assertNotIn(self.info["noise_sha"], shas)

    def test_limits_reported_and_not_truncated(self):
        self.assertFalse(self.result["limits"]["truncated"])
        self.assertEqual(self.result["limits"]["max_commits"], 5000)


class TestRevertSurvivesNoiseFiltering(unittest.TestCase):
    """A revert folded in by a merge commit (N9 noise, 2 parents) must
    stay in revert_chain even when it is reachable only through
    line-history, not through blame, for the target line -- and even
    though noise-filtering correctly excludes it from
    introduction_candidates.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.info = make_fixture_repo.build_revert_merge_noise(self.tmp.name)
        self.result = tracer.trace(
            self.info["repo"], self.info["path"],
            self.info["line"], self.info["line"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_merge_revert_is_not_a_blame_candidate(self):
        blame_shas = [b["sha"] for b in self.result["blame_candidates"]]
        self.assertNotIn(self.info["revert_sha"], blame_shas)

    def test_merge_revert_is_excluded_from_introduction_candidates(self):
        shas = [c["sha"] for c in self.result["introduction_candidates"]]
        self.assertNotIn(self.info["revert_sha"], shas)

    def test_merge_revert_still_appears_in_revert_chain(self):
        shas = [c["sha"] for c in self.result["revert_chain"]]
        self.assertIn(self.info["revert_sha"], shas)


class TestCandidateCap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.info = make_fixture_repo.build_candidate_cap_probe(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_cap_keeps_every_candidate(self):
        result = tracer.trace(
            self.info["repo"], self.info["path"],
            self.info["line"], self.info["line"],
        )
        self.assertGreater(len(result["introduction_candidates"]), 1)
        self.assertFalse(result["limits"]["candidate_cap_reached"])
        self.assertEqual(result["limits"]["max_candidates"], 200)

    def test_small_cap_drops_candidates_and_reports_it(self):
        result = tracer.trace(
            self.info["repo"], self.info["path"],
            self.info["line"], self.info["line"],
            max_candidates=1,
        )
        self.assertLessEqual(len(result["introduction_candidates"]), 1)
        self.assertTrue(result["limits"]["candidate_cap_reached"])
        self.assertEqual(result["limits"]["max_candidates"], 1)
        self.assertTrue(any("cap" in note for note in result["notes"]))


if __name__ == "__main__":
    unittest.main()
