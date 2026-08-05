import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixture_repo


class TestF1Fixture(unittest.TestCase):
    def test_naive_blame_points_at_formatter_commit(self):
        """F1: the fixture must actually poison blame.

        If naive `git blame` returned the real introducing commit, the whole
        premise of this tool would be wrong. This test locks the premise in.
        """
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            out = subprocess.run(
                ["git", "blame", "-L", f"{info['line']},{info['line']}",
                 "--porcelain", info["path"]],
                cwd=info["repo"], capture_output=True, text=True, check=True,
            ).stdout
            blamed_sha = out.split()[0]

            self.assertTrue(blamed_sha.startswith(info["noise_sha"][:7]))
            self.assertFalse(blamed_sha.startswith(info["real_sha"][:7]))


if __name__ == "__main__":
    unittest.main()
