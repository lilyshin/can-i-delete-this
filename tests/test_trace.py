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


if __name__ == "__main__":
    unittest.main()
