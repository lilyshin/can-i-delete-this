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


if __name__ == "__main__":
    unittest.main()
