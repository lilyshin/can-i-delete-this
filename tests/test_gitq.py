import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import gitq


class TestReadOnlyGuard(unittest.TestCase):
    def test_write_commands_are_refused(self):
        for cmd in ["reset", "checkout", "rebase", "push", "commit",
                    "stash", "branch", "merge", "cherry-pick", "clean"]:
            with self.assertRaises(gitq.GitWriteAttempt):
                gitq.run_git("/tmp", [cmd, "--hard"])

    def test_read_commands_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            out = gitq.run_git(info["repo"], ["rev-parse", "HEAD"])
            self.assertEqual(len(out.strip()), 40)


class TestCommitMeta(unittest.TestCase):
    def test_parses_subject_and_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            c = gitq.commit_meta(info["repo"], info["real_sha"])
            self.assertEqual(c.subject, "hotfix: prevent double charge (#4127)")
            self.assertEqual(c.author_email, "fixture@example.com")
            self.assertEqual(c.files_changed, 1)
            self.assertEqual(c.parents_count, 1)
            self.assertTrue(c.date.startswith("2019-11-08"))


class TestPickaxe(unittest.TestCase):
    def test_finds_the_commit_that_introduced_the_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            shas = gitq.pickaxe(info["repo"], "order.already_charged")
            self.assertIn(info["real_sha"], shas)


class TestWhitespaceOnly(unittest.TestCase):
    def test_formatter_commit_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            self.assertTrue(gitq.is_whitespace_only(info["repo"], info["noise_sha"]))
            self.assertFalse(gitq.is_whitespace_only(info["repo"], info["real_sha"]))


if __name__ == "__main__":
    unittest.main()
