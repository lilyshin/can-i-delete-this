"""Build git repositories with booby-trapped history for regression tests.

This module writes git history and runs git commands, which is allowed for test
fixture builders. Read-only git access is enforced in a separate module.
"""

import subprocess
from pathlib import Path

ENV = {
    "GIT_AUTHOR_NAME": "Fixture Author",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture Author",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
}


def _git(repo: Path, *args: str, date: str = None) -> str:
    import os
    env = dict(os.environ)
    env.update(ENV)
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
    """N1: a formatter commit rewrites every line, burying the real author."""
    repo = _init(dest, "f1")
    target = repo / "payment.py"

    target.write_text(
        "def charge(order):\n"
        "    return order.total\n"
    )
    _commit(repo, "feat: add charge", "2019-01-05T10:00:00")

    # The real introduction: a guard added during an incident.
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return order.receipt\n"
        "    return order.total\n"
    )
    real_sha = _commit(repo, "hotfix: prevent double charge (#4127)",
                       "2019-11-08T02:14:00")

    # Noise: a formatter reindents the whole file, rewriting every line.
    target.write_text(
        'def charge(order):\n'
        '    if order.already_charged:\n'
        '         return order.receipt\n'
        '\n'
        '    return order.total\n'
    )
    noise_sha = _commit(repo, "chore: apply formatter", "2023-06-01T09:00:00")

    return {
        "repo": str(repo),
        "path": "payment.py",
        "line": 3,  # `return order.receipt`
        "real_sha": real_sha,
        "noise_sha": noise_sha,
    }
