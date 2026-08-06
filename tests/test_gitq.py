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


class TestLineHistory(unittest.TestCase):
    def _build_multi_edit_repo(self, tmp):
        repo = Path(tmp) / "line_hist"
        repo.mkdir()
        make_fixture_repo._git(repo, "init", "-q", "-b", "main")
        target = repo / "a.py"
        for i in range(3):
            target.write_text("VALUE = {}\n".format(i))
            make_fixture_repo._commit(repo, "chore: edit {}".format(i),
                                       make_fixture_repo._days_ago(300 - i * 10))
        return str(repo)

    def test_max_commits_is_forwarded_to_git_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build_multi_edit_repo(tmp)
            unbounded = gitq.line_history(repo, "a.py", 1, 1)
            self.assertEqual(len(unbounded), 3)

            bounded = gitq.line_history(repo, "a.py", 1, 1, max_commits=1)
            self.assertEqual(len(bounded), 1)

    def test_since_is_forwarded_to_git_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build_multi_edit_repo(tmp)
            future_only = gitq.line_history(repo, "a.py", 1, 1, since="1 second ago")
            self.assertEqual(future_only, [])


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


class TestQuotepathOffCarveOut(unittest.TestCase):
    """The `-c core.quotepath=off` carve-out in run_git must be narrow: it
    matches exactly that two-token prefix and nothing else, and everything
    after it is still checked against ALLOWED and WRITE_FLAG_PREFIXES as if
    the prefix were not there. The four vectors below are the historical
    bypasses this project's read-only guard was built against; all four
    must still be refused with this carve-out in place.
    """

    def test_carve_out_permits_the_documented_read_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            out = gitq.run_git(info["repo"], [
                "-c", "core.quotepath=off", "show", "--name-only",
                "--format=", info["real_sha"],
            ])
            self.assertTrue(out.strip())

    def test_historical_bypass_global_flag_before_subcommand(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["-c", "user.email=x", "commit", "--allow-empty", "-m", "x"])

    def test_historical_bypass_unknown_alias_subcommand(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["co", "other"])

    def test_historical_bypass_config_subcommand(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["config", "user.email", "x"])

    def test_historical_bypass_output_flag(self):
        output_file = str(Path(_TEST_TMPDIR) / "should-not-exist-cidt3")
        Path(output_file).unlink(missing_ok=True)
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["log", "-1", "--output=" + output_file])
        self.assertFalse(Path(output_file).exists())

    def test_carve_out_prefix_does_not_launder_a_write_subcommand(self):
        # Same known-safe prefix, but a write subcommand right after it:
        # the carve-out must not become a generic "anything after -c is
        # fine" hole.
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["-c", "core.quotepath=off", "commit", "-m", "x"])

    def test_carve_out_prefix_does_not_permit_a_second_config_flag(self):
        # A near-miss of the known-safe prefix: the same two tokens, plus
        # more config injected right after. rest[0] after stripping the
        # exact prefix is still "-c", which must still be refused.
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", [
                "-c", "core.quotepath=off", "-c", "user.email=x",
                "commit", "--allow-empty", "-m", "x",
            ])

    def test_near_miss_quotepath_value_is_not_carved_out(self):
        # Not the exact known-safe value: must fall through to the normal
        # leading-dash refusal, not be treated as the carve-out.
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["-c", "core.quotepath=true", "log"])


if __name__ == "__main__":
    unittest.main()
