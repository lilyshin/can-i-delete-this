import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import gitq


_TEST_TMPDIR = tempfile.gettempdir()


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


class TestBypassAttempts(unittest.TestCase):
    def test_global_flag_before_subcommand_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["-c", "user.email=x", "commit", "--allow-empty", "-m", "x"])

    def test_unknown_subcommand_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["co", "other"])

    def test_config_subcommand_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["config", "user.email", "x"])

    def test_output_flag_in_log_is_refused(self):
        output_file = str(Path(_TEST_TMPDIR) / "should-not-exist-cidt")
        Path(output_file).unlink(missing_ok=True)
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["log", "-1", "--output=" + output_file])
        self.assertFalse(Path(output_file).exists(), "File should not be created when write flag is blocked")

    def test_output_flag_in_diff_is_refused(self):
        output_file = str(Path(_TEST_TMPDIR) / "should-not-exist-cidt2")
        Path(output_file).unlink(missing_ok=True)
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["diff", "--output=" + output_file, "HEAD", "HEAD"])
        self.assertFalse(Path(output_file).exists(), "File should not be created when write flag is blocked")


if __name__ == "__main__":
    unittest.main()
