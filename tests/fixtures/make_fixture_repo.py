"""Build git repositories with booby-trapped history for regression tests.

This module writes git history and runs git commands, which is allowed for test
fixture builders. Read-only git access is enforced in a separate module.
"""

import os
import subprocess
from pathlib import Path

ENV = {
    "GIT_AUTHOR_NAME": "Fixture Author",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture Author",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
}


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
    """
    repo = _init(dest, "f1")
    target = repo / "payment.py"
    extra_files = [repo / "file_{:02d}.py".format(i) for i in range(24)]

    target.write_text(
        "def charge(order):\n"
        "    return order.total\n"
    )
    for f in extra_files:
        f.write_text("x = 'value_{}'\n".format(f.stem))
    _commit(repo, "feat: add charge", "2019-01-05T10:00:00")

    # The real introduction: a guard added during an incident.
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return {'status': 'duplicate'}\n"
        "    return order.total\n"
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
        "    return order.total\n"
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
