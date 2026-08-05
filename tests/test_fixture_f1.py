import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import gitq


class TestF1Fixture(unittest.TestCase):
    def test_blame_still_points_at_formatter_with_whitespace_and_move_detection_on(self):
        """F1: the fixture must poison blame even with every git-native
        noise-resistance option turned on.

        gitq.blame_shas runs `git blame -w -C -C -C`: ignore whitespace,
        and detect moved/copied lines. If that already resolved through the
        formatter commit on its own, there would be nothing left for this
        tool's noise-scoring and pickaxe fallback to do -- the problem
        would already be solved by git itself. This test locks in the real
        premise: calling gitq.blame_shas exactly as trace.py will call it
        still lands on the formatter commit, not the real introducing one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            shas = gitq.blame_shas(info["repo"], info["path"], info["line"], info["line"])

            self.assertEqual(shas[0], info["noise_sha"])
            self.assertNotEqual(shas[0], info["real_sha"])


class TestDeepHistoryFixture(unittest.TestCase):
    """Regression coverage for the pressure/pressure-truncate.md fixture:
    it must actually be deep (113 commits planted), and the real
    introducing commit must actually be in that history, buried behind the
    formatter commit blame reports. This does not test trace.py or any
    tool under skills/ -- tests/pressure's scenarios run a bare subagent
    against this repo with no tooling, so the only thing worth locking in
    here is that the fixture builder itself keeps producing the shape the
    scenario depends on.
    """

    def test_113_commits_planted_with_real_fix_buried_in_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_deep_history(tmp)

            log = subprocess.run(
                ["git", "log", "--oneline", "--", info["path"]],
                cwd=info["repo"], capture_output=True, text=True, check=True,
            ).stdout.strip().splitlines()

            self.assertEqual(len(log), info["total_commits"])
            self.assertEqual(len(log), 113)

            subjects = "\n".join(log)
            self.assertIn("reject replayed session tokens after logout (#5521)", subjects)
            self.assertIn(info["real_sha"][:7], subjects)

            # blame must land on the formatter commit, not the real fix,
            # confirming the real commit is genuinely buried rather than
            # trivially discoverable from a single blame call.
            shas = gitq.blame_shas(info["repo"], info["path"], info["line"], info["line"])
            self.assertEqual(shas[0], info["noise_sha"])
            self.assertNotEqual(shas[0], info["real_sha"])


if __name__ == "__main__":
    unittest.main()
