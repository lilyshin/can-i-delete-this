import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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


class TestRunGitBytes(unittest.TestCase):
    """`run_git_bytes` (added for trace.py's line-break-divergence fix,
    see test_trace_line_break_divergence.py) shares `run_git`'s guard
    through the same `_run_git_subprocess` helper; this pins that the
    guard actually still applies to the new entry point, not just to
    `run_git`, and that the one thing `run_git_bytes` exists for --
    stdout bytes with no universal-newline translation -- actually
    holds."""

    def test_write_commands_are_refused(self):
        for cmd in ["reset", "checkout", "rebase", "push", "commit",
                    "stash", "branch", "merge", "cherry-pick", "clean"]:
            with self.assertRaises(gitq.GitWriteAttempt):
                gitq.run_git_bytes("/tmp", [cmd, "--hard"])

    def test_returns_bytes_not_str(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            out = gitq.run_git_bytes(info["repo"], ["rev-parse", "HEAD"])
            self.assertIsInstance(out, bytes)
            self.assertEqual(len(out.strip()), 40)

    def test_a_lone_carriage_return_survives_undisturbed(self):
        # The one guarantee `run_git` cannot make: `run_git`'s text mode
        # rewrites a lone "\r" to "\n" via universal-newline translation
        # before a caller ever sees it (see `run_git_bytes`'s docstring).
        # `run_git_bytes` must hand back the byte git actually stored.
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_line_break_divergence(tmp, divergent=b"\r")
            raw = gitq.run_git_bytes(info["repo"], ["show", "HEAD:" + info["path"]])
            self.assertIn(b"\r", raw)
            translated = gitq.run_git(info["repo"], ["show", "HEAD:" + info["path"]])
            self.assertNotIn("\r", translated)


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


class TestGrepAllowed(unittest.TestCase):
    """`grep` is a read-only subcommand (searches the working tree, never
    writes), added to ALLOWED for needle-rarity probing in trace.py's
    needle selection. Its own historical write-adjacent risk,
    `--open-files-in-pager`, is already covered by WRITE_FLAG_PREFIXES.
    """

    def test_grep_passes_the_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            out = gitq.run_git(info["repo"], ["grep", "-l", "-F", "-e", "charge"],
                                ok_returncodes=(0, 1))
            self.assertIn("payment.py", out)

    def test_grep_open_files_in_pager_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["grep", "--open-files-in-pager=vi", "x"])


class TestGrepMatchFileCount(unittest.TestCase):
    def test_counts_files_containing_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            count = gitq.grep_match_file_count(info["repo"], "already_charged")
            self.assertEqual(count, 1)

    def test_zero_matches_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            count = gitq.grep_match_file_count(info["repo"], "no_such_token_anywhere")
            self.assertEqual(count, 0)


def _write_marker_pager(directory):
    """A fake `core.pager` program: writes a marker file if it ever runs,
    and does nothing else. Returns (script_path, marker_path).
    """
    marker = Path(directory) / "pager_was_called"
    script = Path(directory) / "fake_pager.sh"
    script.write_text("#!/bin/sh\necho called > {}\n".format(marker))
    script.chmod(0o755)
    return script, marker


class TestGrepOpenFilesInPagerShortForm(unittest.TestCase):
    """`git grep -O` (the short form of --open-files-in-pager) launches
    core.pager/$GIT_PAGER as a real subprocess with matched file paths as
    arguments; WRITE_FLAG_PREFIXES only matched the long form until this
    fix. `-O` accepts an attached value (`-Ovim`), so the guard must be a
    prefix match, and the same short form is dangerous for `log`/`diff`
    too since they accept the same flag.
    """

    def test_grep_dash_o_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["grep", "-O", "x"])

    def test_grep_dash_o_with_attached_value_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["grep", "-Ovim", "x"])

    def test_log_dash_o_with_attached_value_is_refused(self):
        with self.assertRaises(gitq.GitWriteAttempt):
            gitq.run_git("/tmp", ["log", "-O/tmp/f", "-1"])


class TestPagerExecutionIsSanitized(unittest.TestCase):
    """The flag guard above proves run_git *refuses* to run `grep -O`.
    That alone would miss an ordering bug: if some future change let a
    pager-triggering call reach `subprocess.run` without going through
    that check (a different flag this project has not thought of, a typo
    in the prefix list, ...), would the environment and config gitq
    forces onto every invocation still have prevented real execution?
    These tests answer that directly, by observing whether a malicious
    `core.pager`/`$GIT_PAGER` program actually ran (a file it would have
    written), not by checking for an exception. "Only checking the
    exception misses ordering problems": a test that merely asserts
    GitWriteAttempt was raised would still pass if _SAFE_GIT_CONFIG or
    _SAFE_ENV_OVERRIDES were silently broken, since the guard runs before
    either ever gets a chance to matter for *this* input; these tests
    apply gitq's own safety constants exactly as run_git does and run the
    dangerous command directly, so a regression in the constants
    themselves, not just in the guard, would be caught.
    """

    def test_premise_a_repo_local_pager_really_is_exploitable_unguarded(self):
        # Pin that this is a real vulnerability, not a hypothetical: with
        # none of gitq's defenses applied, plain `git grep -O` in a repo
        # whose local config points core.pager at our script really does
        # run that script.
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            script, marker = _write_marker_pager(tmp)
            subprocess.run(["git", "config", "core.pager", str(script)],
                            cwd=info["repo"], check=True)
            subprocess.run(["git", "grep", "-O", "-F", "-e", "charge"],
                            cwd=info["repo"], capture_output=True, text=True)
            self.assertTrue(marker.exists(),
                             "premise: without any defense this repo-local "
                             "core.pager really is exploitable via -O")

    def test_repo_local_pager_config_is_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            script, marker = _write_marker_pager(tmp)
            subprocess.run(["git", "config", "core.pager", str(script)],
                            cwd=info["repo"], check=True)

            env = dict(os.environ)
            env.update(gitq._SAFE_ENV_OVERRIDES)
            subprocess.run(
                ["git", *gitq._SAFE_GIT_CONFIG, "grep", "-O", "-F", "-e", "charge"],
                cwd=info["repo"], capture_output=True, text=True, env=env,
            )
            self.assertFalse(
                marker.exists(),
                "core.pager script must never run once gitq's safe "
                "config/env are applied, even for -O")

    def test_hostile_ambient_git_pager_environment_variable_is_overridden(self):
        # The config override above is not enough on its own: a GIT_PAGER
        # environment variable set by whatever process launches this
        # tool wins over `-c core.pager` on the command line (confirmed
        # empirically). _SAFE_ENV_OVERRIDES must win over that too.
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            script, marker = _write_marker_pager(tmp)
            with unittest.mock.patch.dict(os.environ, {"GIT_PAGER": str(script)}):
                env = dict(os.environ)
                env.update(gitq._SAFE_ENV_OVERRIDES)
                subprocess.run(
                    ["git", *gitq._SAFE_GIT_CONFIG, "grep", "-O", "-F", "-e", "charge"],
                    cwd=info["repo"], capture_output=True, text=True, env=env,
                )
            self.assertFalse(
                marker.exists(),
                "a hostile ambient GIT_PAGER must not survive "
                "_SAFE_ENV_OVERRIDES")

    def test_run_git_itself_never_creates_the_marker_for_an_allowed_grep(self):
        # End-to-end through the real public API (no -O involved, since
        # that is refused before reaching subprocess at all): a normal,
        # allowed grep call in a repo with a hostile core.pager must not
        # trigger it either.
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            script, marker = _write_marker_pager(tmp)
            subprocess.run(["git", "config", "core.pager", str(script)],
                            cwd=info["repo"], check=True)
            gitq.run_git(info["repo"], ["grep", "-l", "-F", "-e", "charge"])
            self.assertFalse(marker.exists())


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


class TestBlameRevision(unittest.TestCase):
    """A caller whose line numbers came from a committed revision must be
    able to blame that same revision. Without it, one uncommitted edit
    makes `blame -L` answer for whichever lines the working tree happens to
    hold at those numbers."""

    def test_default_argv_is_unchanged(self):
        """trace.py calls this with three arguments and prints the result as
        a reproduction command; it must keep running and displaying exactly
        what it does today."""
        self.assertEqual(
            gitq.blame_args("src/a.py", 10, 12),
            ["blame", "-w", "-C", "-C", "-C", "--porcelain", "-L", "10,12",
             "--", "src/a.py"])

    def test_revision_is_placed_where_git_expects_it(self):
        self.assertEqual(
            gitq.blame_args("src/a.py", 10, 12, rev="HEAD"),
            ["blame", "-w", "-C", "-C", "-C", "--porcelain", "-L", "10,12",
             "HEAD", "--", "src/a.py"])

    def test_blaming_head_ignores_an_uncommitted_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_commented_out(tmp)
            target = os.path.join(info["repo"], "billing.py")
            with open(target, encoding="utf-8") as fh:
                text = fh.read()
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text.replace("range(3)", "range(9)"))

            head = gitq.blame_shas(info["repo"], "billing.py", 2, 6, rev="HEAD")
            self.assertEqual(head, [info["outage_sha"]], head)


class TestZeroShaIsRejected(unittest.TestCase):
    """git prints the all-zeros sha for a line that is not committed yet.
    It is 40 hex characters and passes every other shape check, so it used
    to reach `commit_meta`, which raises `fatal: bad object`. It can never
    name a commit, so it is dropped where blame output is parsed rather
    than in each caller."""

    def test_uncommitted_lines_are_dropped_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_commented_out(tmp)
            target = os.path.join(info["repo"], "billing.py")
            with open(target, encoding="utf-8") as fh:
                text = fh.read()
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text.replace("range(3)", "range(9)"))

            # No rev: this blames the working tree, where line 3 is the
            # edited, uncommitted line.
            shas = gitq.blame_shas(info["repo"], "billing.py", 3, 3)
            self.assertNotIn(gitq.ZERO_SHA, shas)
            self.assertEqual(shas, [])

    def test_the_premise_is_that_git_really_prints_the_zero_sha(self):
        """If a future git stops using the all-zeros marker, this test says
        so instead of the filter above passing for the wrong reason."""
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_commented_out(tmp)
            target = os.path.join(info["repo"], "billing.py")
            with open(target, encoding="utf-8") as fh:
                text = fh.read()
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text.replace("range(3)", "range(9)"))

            raw = gitq.run_git(info["repo"],
                               gitq.blame_args("billing.py", 3, 3))
            self.assertIn(gitq.ZERO_SHA, raw)


if __name__ == "__main__":
    unittest.main()
