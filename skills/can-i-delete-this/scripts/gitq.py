"""Read-only git query layer.

Every git call in this project goes through run_git so the write-command
guard cannot be bypassed.
"""

import re
import subprocess
from dataclasses import dataclass

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

ALLOWED = frozenset({
    "blame", "log", "show", "diff", "rev-parse", "rev-list",
    "cat-file", "ls-files", "ls-tree", "merge-base", "name-rev",
    "describe", "for-each-ref", "shortlog", "var",
})

WRITE_FLAG_PREFIXES = (
    "--output",
    "--textconv",
    "--ext-diff",
    "--exec",
    "--upload-pack",
    "--receive-pack",
    "--open-files-in-pager",
)

_SEP = "\x1f"
_FMT = _SEP.join(["%H", "%an", "%ae", "%aI", "%s", "%P", "%b"])


class GitWriteAttempt(RuntimeError):
    """Raised when code tries to run a git command that mutates state."""


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    author_email: str
    date: str
    subject: str
    body: str
    parents_count: int
    files_changed: int
    insertions: int
    deletions: int


def run_git(repo, args):
    if not args:
        raise GitWriteAttempt("empty git invocation")
    if args[0].startswith("-"):
        raise GitWriteAttempt("refusing to run git with global flags: " + args[0])
    if args[0] not in ALLOWED:
        raise GitWriteAttempt("refusing to run git subcommand: " + args[0])
    for arg in args:
        for prefix in WRITE_FLAG_PREFIXES:
            if arg.startswith(prefix):
                raise GitWriteAttempt("refusing to run git with write flag: " + arg)
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + " failed: " + proc.stderr.strip())
    return proc.stdout


def commit_meta(repo, sha):
    raw = run_git(repo, ["show", "-s", "--format=" + _FMT, sha]).rstrip("\n")
    sha_, an, ae, date, subject, parents, body = raw.split(_SEP, 6)
    added, removed, files = 0, 0, 0
    numstat = run_git(repo, ["show", "--first-parent", "--numstat", "--format=", sha])
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        files += 1
        if parts[0].isdigit():
            added += int(parts[0])
        if parts[1].isdigit():
            removed += int(parts[1])
    return Commit(
        sha=sha_, author=an, author_email=ae, date=date, subject=subject,
        body=body.strip(), parents_count=len(parents.split()) if parents else 0,
        files_changed=files, insertions=added, deletions=removed,
    )


def blame_shas(repo, path, start, end):
    out = run_git(repo, [
        "blame", "-w", "-C", "-C", "-C", "--porcelain",
        "-L", "{},{}".format(start, end), "--", path,
    ])
    shas = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and len(parts[0]) == 40 and parts[0] not in shas:
            try:
                int(parts[1])
                int(parts[2])
            except ValueError:
                continue
            shas.append(parts[0])
    return shas


def pickaxe(repo, needle, path=None, max_commits=5000, since=None):
    args = ["log", "--format=%H", "-S", needle, "--max-count={}".format(max_commits)]
    if since:
        args.append("--since=" + since)
    if path:
        args.extend(["--", path])
    return run_git(repo, args).split()


def line_history(repo, path, start, end, max_commits=None, since=None):
    args = ["log", "--format=%H", "-L", "{},{}:{}".format(start, end, path)]
    if max_commits:
        args.append("--max-count={}".format(max_commits))
    if since:
        args.append("--since=" + since)
    out = run_git(repo, args)
    return [l for l in out.split("\n") if _SHA_RE.match(l)]


def changed_paths(repo, sha):
    out = run_git(repo, ["show", "--name-only", "--format=", sha])
    return [p for p in out.splitlines() if p.strip()]


def is_whitespace_only(repo, sha):
    """True when the commit changes nothing once whitespace is ignored."""
    parent = sha + "^"
    try:
        diff = run_git(repo, ["diff", "-w", "--ignore-blank-lines", "--numstat", parent, sha])
    except RuntimeError:
        return False
    for line in diff.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and (parts[0] not in ("0", "-") or parts[1] not in ("0", "-")):
            return False
    return True
