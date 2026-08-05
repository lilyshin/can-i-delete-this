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
    def test_pure_reindent_commit_is_detected(self):
        # F1's formatter commit changes quote tokens (see make_fixture_repo),
        # not just whitespace, precisely so it survives `blame -w`. So a
        # dedicated pure-whitespace commit is used here to verify
        # is_whitespace_only's own true-positive case.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "ws"
            repo.mkdir()
            make_fixture_repo._git(repo, "init", "-q", "-b", "main")
            target = repo / "a.py"
            target.write_text("def f():\n    return 1\n")
            make_fixture_repo._commit(repo, "feat: add f", "2020-01-01T00:00:00")
            target.write_text("def f():\n        return 1\n")
            reindent_sha = make_fixture_repo._commit(repo, "chore: reindent", "2020-01-02T00:00:00")
            self.assertTrue(gitq.is_whitespace_only(str(repo), reindent_sha))

    def test_f1_formatter_commit_is_token_level_not_whitespace_only(self):
        # The redesigned F1 formatter changes quote characters (a real
        # token, content-level change) so that it survives `blame -w`.
        # is_whitespace_only must correctly report this as not
        # whitespace-only; noise.py's keyword+breadth path is what flags
        # it as noise instead (covered in test_trace.py and test_noise.py).
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            self.assertFalse(gitq.is_whitespace_only(info["repo"], info["noise_sha"]))
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
