"""Build git repositories with booby-trapped history for regression tests.

This module writes git history and runs git commands, which is allowed for test
fixture builders. Read-only git access is enforced in a separate module.
"""

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ENV = {
    "GIT_AUTHOR_NAME": "Fixture Author",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture Author",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
}


def _days_ago(days: int) -> str:
    """A commit date `days` days before "now".

    Not used by the fixture builders below: their commit dates are fixed
    (trace()'s default `since` is None, so there is no rolling window for
    a fixed historical date to age out of, and fixed dates keep those
    tests deterministic). This helper remains for tests that specifically
    exercise an explicit, relative `since` cutoff (e.g. TestLineHistory in
    test_gitq.py), where "N days before whenever this runs" is exactly
    the relationship being tested.
    """
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def _git(repo: Path, *args: str, date: str = None) -> str:
    env = dict(os.environ)
    env.update(ENV)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        check=True, env=env,
    ).stdout.strip()


def _init(dest: str, name: str) -> Path:
    repo = Path(dest) / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    return repo


def _commit(repo: Path, message: str, date: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, date=date)
    return _git(repo, "rev-parse", "HEAD")


def build_f1(dest: str) -> dict:
    """N1: a repo-wide formatter commit flips string-quote style, burying
    the real author of the target line.

    `git blame -w` only ignores whitespace, so a formatter that merely
    reindents can be seen through by blame on its own, with nothing left
    for noise-scoring or the pickaxe fallback to do. Real formatters
    (black, prettier, ...) also rewrite tokens, e.g. unifying quote
    characters. That is a content change, not a whitespace change, so it
    survives `git blame -w -C -C -C` (the exact invocation
    gitq.blame_shas uses, including copy/move detection). The formatter
    commit also touches enough files to clear noise.py's
    BREADTH_THRESHOLD, so its "chore: apply formatter" subject is enough
    for noise.score to flag it under N1 even though the diff is no longer
    whitespace-only.

    Dates are fixed (not relative to "now"): trace()'s default `since` is
    None (no time bound at all -- an archaeology tool for old code cannot
    default to ignoring old code), so there is no rolling window for a
    fixed historical date to age out of, and fixed dates keep this test
    deterministic across runs.
    """
    repo = _init(dest, "f1")
    target = repo / "payment.py"
    extra_files = [repo / "file_{:02d}.py".format(i) for i in range(24)]

    # The base line deliberately avoids the word "return": it is one of the
    # target line's pickaxe needles (see _needles in trace.py). Since
    # trace()'s default `since` is None, pickaxe searches full history by
    # default with no date cutoff, so if this base commit also introduced
    # "return" it would be a second, older, non-noise pickaxe hit that
    # outranks the real fix by date -- this is independent of whether
    # dates are fixed or relative. It is also kept byte-identical across
    # every later commit so the guard clause is a pure insertion above it,
    # not a rewrite of it; git's line-history (-L) walks back through
    # rewritten lines, and this fixture wants the real fix to be the
    # line's true origin.
    target.write_text(
        "def charge(order):\n"
        "    order.mark_processed()\n"
    )
    for f in extra_files:
        f.write_text("x = 'value_{}'\n".format(f.stem))
    _commit(repo, "feat: add charge", "2019-01-05T10:00:00")

    # The real introduction: a guard added during an incident.
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return {'status': 'duplicate'}\n"
        "    order.mark_processed()\n"
    )
    real_sha = _commit(repo, "hotfix: prevent double charge (#4127)",
                       "2019-11-08T02:14:00")

    # Noise: a repo-wide formatter flips single quotes to double quotes
    # across every file, including the target line. Token-level change,
    # not whitespace, and wide enough to clear the breadth threshold.
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        '        return {"status": "duplicate"}\n'
        "    order.mark_processed()\n"
    )
    for f in extra_files:
        f.write_text('x = "value_{}"\n'.format(f.stem))
    noise_sha = _commit(repo, "chore: apply formatter", "2023-06-01T09:00:00")

    return {
        "repo": str(repo),
        "path": "payment.py",
        "line": 3,  # `return {"status": "duplicate"}` (post-formatter)
        "real_sha": real_sha,
        "noise_sha": noise_sha,
    }


def build_revert_merge_noise(dest: str) -> dict:
    """A GitHub-style revert folded back in by an actual merge commit
    (2 parents), reachable through line-history but not through blame or
    pickaxe for the target line.

    Not F5: F5 (revert-then-reintroduce) is a separate, later fixture.

    Regression fixture for the requirement that revert_chain survive
    noise filtering, without leaning on blame (a real merge commit's own
    sha is not attainable through gitq.pickaxe(): git suppresses merge
    diffs from `-S` unless --first-parent/-m/--full-history is added,
    which gitq.pickaxe() does not do). Two branches independently touch
    the same line after diverging, so merging them conflicts and must be
    resolved by hand; git blame would normally attribute a genuinely
    resolved conflict line to the merge commit itself, but one further
    small commit lands after the merge and touches that same line again,
    so blame's current attribution moves past the merge commit while
    line-history's full lineage still walks through it. noise.score
    classifies the merge N9 (parents_count=2) unconditionally, so add()
    would have discarded it before revert_chain ever saw it, unless
    revert_chain is collected from every sha encountered along a search
    path regardless of its noise verdict.
    """
    repo = _init(dest, "revert_merge_noise")
    target = repo / "feature.py"

    target.write_text("ENABLED_FEATURES = []\n")
    _commit(repo, "chore: base", "2020-01-01T10:00:00")

    target.write_text('ENABLED_FEATURES = ["quota_guard_v2"]\n')
    _commit(repo, "feat: real change", "2020-03-01T10:00:00")

    _git(repo, "checkout", "-q", "-b", "revert-branch")
    target.write_text("ENABLED_FEATURES = []\n")
    _commit(repo, 'Revert "feat: real change"', "2020-05-01T10:00:00")

    _git(repo, "checkout", "-q", "main")
    target.write_text('ENABLED_FEATURES = ["quota_guard_v2", "extra_flag"]\n')
    _commit(repo, "chore: unrelated tweak", "2020-04-15T10:00:00")

    # This merge conflicts by construction: main and revert-branch each
    # changed the same line differently since diverging. Let it fail, then
    # resolve by hand and finish the commit through the usual helper.
    env = dict(os.environ)
    env.update(ENV)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(
        ["git", "merge", "--no-ff", "-q", "-m",
         'Revert "feat: real change" (#9)', "revert-branch"],
        cwd=repo, capture_output=True, text=True, env=env,
    )
    target.write_text('ENABLED_FEATURES = ["extra_flag"]\n')
    revert_sha = _commit(repo, 'Revert "feat: real change" (#9)', "2020-05-02T10:00:00")

    # One further, unrelated small edit after the merge so blame's current
    # attribution for line 1 moves past the merge commit, while line-history
    # still walks through it as part of the line's full lineage.
    target.write_text('ENABLED_FEATURES = ["extra_flag", "cosmetic"]\n')
    _commit(repo, "chore: cosmetic tweak", "2020-06-01T10:00:00")

    return {
        "repo": str(repo),
        "path": "feature.py",
        "line": 1,
        "revert_sha": revert_sha,
    }


def build_candidate_cap_probe(dest: str) -> dict:
    """A target line whose distinctive token also appears, one at a time,
    in three unrelated commits touching three unrelated files.

    Regression fixture for trace()'s total-candidate cap (max_candidates).
    The target file's own commit is found through blame (exempt from the
    cap); the three unrelated commits are only found through pickaxe, so
    they are exactly the kind of addition the cap is meant to bound. With
    a very small max_candidates, at least one of them must be dropped and
    reported, while the default max_candidates must keep all of them.
    """
    repo = _init(dest, "candidate_cap_probe")
    target = repo / "target.py"

    target.write_text('MAGIC = "zzz_needle_token"\n')
    _commit(repo, "feat: add magic", "2019-01-01T10:00:00")

    for i in range(1, 4):
        other = repo / "other{}.py".format(i)
        other.write_text('X = "zzz_needle_token"\n')
        _commit(repo, "feat: mention token in other{}".format(i),
                "2019-01-0{}T10:00:00".format(i + 1))

    return {
        "repo": str(repo),
        "path": "target.py",
        "line": 1,
    }
