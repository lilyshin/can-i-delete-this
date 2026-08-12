"""Read-only git query layer.

Every git call in this project goes through run_git so the write-command
guard cannot be bypassed.
"""

import os
import re
import subprocess
from dataclasses import dataclass

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

ALLOWED = frozenset({
    "blame", "log", "show", "diff", "rev-parse", "rev-list",
    "cat-file", "ls-files", "ls-tree", "merge-base", "name-rev",
    "describe", "for-each-ref", "shortlog", "var", "grep",
})

WRITE_FLAG_PREFIXES = (
    "--output",
    "--textconv",
    "--ext-diff",
    "--exec",
    "--upload-pack",
    "--receive-pack",
    "--open-files-in-pager",
    # Short form of --open-files-in-pager for `git grep`: launches
    # core.pager/$GIT_PAGER as a real subprocess with matched file paths
    # as arguments, confirmed by direct experiment against this project's
    # own read-only guard, unlike ordinary pager use it is not gated by
    # whether stdout is a terminal. `-O` is also the order-file flag for
    # `git log`/`git diff` (a read-only feature this project never uses),
    # so blocking it there too costs nothing. Prefix match, not equality:
    # git accepts an attached value (`-Ovim`, `-O/path/to/orderfile`).
    "-O",
)

# Config forced onto every invocation this module makes, regardless of
# subcommand or what the caller passed, on top of the WRITE_FLAG_PREFIXES
# checks above:
#   core.pager=cat: closes the *config* half of the `-O` exec vector (a
#   hostile repo's own committed-or-local config, not just the ambient
#   environment, can set core.pager). `-c` on the command line overrides
#   repo-local config. It does not override a `GIT_PAGER` environment
#   variable, though (confirmed empirically: env wins over `-c
#   core.pager`), which is why _SAFE_ENV_OVERRIDES below also forces
#   GIT_PAGER; the two together close both the config and the environment
#   route to the same vector.
#   diff.external=: no production call in this module renders an actual
#   diff body today (every diff/show call below uses --numstat/--name-only,
#   confirmed by direct experiment to never consult diff.external
#   regardless of its value), so this is pre-emptive, not a fix for a
#   currently reachable path. Forcing it to empty is a no-op for those
#   calls; it would make a *future* diff-rendering call that forgets
#   `--no-ext-diff` fail loudly with a git error instead of silently
#   executing whatever a repo's own config names.
_SAFE_GIT_CONFIG = ("-c", "core.pager=cat", "-c", "diff.external=")

# Environment overrides applied to every git subprocess this module spawns,
# alongside _SAFE_GIT_CONFIG above. Each of these names a program git will
# execute on our behalf under some condition; none of those conditions are
# ones this read-only query layer ever wants satisfied.
#   GIT_PAGER, PAGER: see _SAFE_GIT_CONFIG's core.pager note. GIT_PAGER
#   wins over both core.pager and PAGER when set; PAGER is git's fallback
#   when neither GIT_PAGER nor core.pager is configured at all.
#   GIT_EXTERNAL_DIFF: the environment-variable twin of diff.external;
#   same reasoning as _SAFE_GIT_CONFIG's entry for it.
#   GIT_EDITOR, GIT_SEQUENCE_EDITOR: this project never runs a git command
#   that should open an editor, but a hostile repo's config (core.editor)
#   or the ambient environment could still try to make one of the
#   subcommands here launch one.
#   GIT_ASKPASS, SSH_ASKPASS: would let git exec a credential-prompt
#   program; moot with no network access anywhere in this project, cheap
#   insurance to force off regardless.
# GIT_CONFIG_GLOBAL and GIT_CONFIG_SYSTEM are deliberately NOT overridden
# here: respecting the caller's own git config when reading the caller's
# own repository is an intentional design choice for this module, the
# opposite of the fixture builders in tests/fixtures/make_fixture_repo.py,
# which set those two to os.devnull for a different reason entirely
# (deterministic throwaway test repos, not attacker-controlled ones).
_SAFE_ENV_OVERRIDES = {
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GIT_EXTERNAL_DIFF": "",
    "GIT_EDITOR": "true",
    "GIT_SEQUENCE_EDITOR": "true",
    "GIT_ASKPASS": "true",
    "SSH_ASKPASS": "true",
}

# The one, narrow, known-safe exception to "args[0] may not start with a
# dash": `-c core.quotepath=off` so non-ASCII paths come back as real UTF-8
# instead of git's default octal-escaped, double-quoted form (see
# `changed_paths`). This is not a general allowance for leading-dash
# arguments; it matches this exact two-token prefix only, and whatever
# follows it is still validated against ALLOWED and WRITE_FLAG_PREFIXES
# exactly as if the prefix were not there. See test_gitq.py's
# TestBypassAttempts for the historical bypass vectors this must keep
# refusing even with this carve-out in place.
_QUOTEPATH_OFF_PREFIX = ("-c", "core.quotepath=off")

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


def run_git(repo, args, ok_returncodes=(0,)):
    if not args:
        raise GitWriteAttempt("empty git invocation")
    # Strip exactly the known-safe `-c core.quotepath=off` prefix, if
    # present, before validating the subcommand. Anything else starting
    # with a dash, including a near-miss of this same prefix followed by
    # more flags, still hits the checks below unchanged.
    rest = args[2:] if tuple(args[:2]) == _QUOTEPATH_OFF_PREFIX else args
    if not rest:
        raise GitWriteAttempt("empty git invocation")
    if rest[0].startswith("-"):
        raise GitWriteAttempt("refusing to run git with global flags: " + rest[0])
    if rest[0] not in ALLOWED:
        raise GitWriteAttempt("refusing to run git subcommand: " + rest[0])
    for arg in args:
        for prefix in WRITE_FLAG_PREFIXES:
            if arg.startswith(prefix):
                raise GitWriteAttempt("refusing to run git with write flag: " + arg)
    env = dict(os.environ)
    env.update(_SAFE_ENV_OVERRIDES)
    proc = subprocess.run(
        ["git", *_SAFE_GIT_CONFIG, *args], cwd=repo, capture_output=True, text=True,
        env=env,
    )
    if proc.returncode not in ok_returncodes:
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


def blame_args(path, start, end):
    """The exact argv `blame_shas` passes to `run_git`, exposed so callers
    that need to *display* the command (the reproduction-commands section
    of the report) can show the literal invocation instead of a
    hand-written approximation that could drift from what actually runs.
    """
    return [
        "blame", "-w", "-C", "-C", "-C", "--porcelain",
        "-L", "{},{}".format(start, end), "--", path,
    ]


def blame_shas(repo, path, start, end):
    out = run_git(repo, blame_args(path, start, end))
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


def pickaxe_args(needle, path=None, max_commits=5000, since=None):
    """The exact argv `pickaxe` passes to `run_git`; see `blame_args`."""
    args = ["log", "--format=%H", "-S", needle, "--max-count={}".format(max_commits)]
    if since:
        args.append("--since=" + since)
    if path:
        args.extend(["--", path])
    return args


def pickaxe(repo, needle, path=None, max_commits=5000, since=None):
    return run_git(repo, pickaxe_args(needle, path=path, max_commits=max_commits,
                                       since=since)).split()


def line_history_args(path, start, end, max_commits=None, since=None):
    """The exact argv `line_history` passes to `run_git`; see `blame_args`."""
    args = ["log", "--format=%H", "-L", "{},{}:{}".format(start, end, path)]
    if max_commits:
        args.append("--max-count={}".format(max_commits))
    if since:
        args.append("--since=" + since)
    return args


def line_history(repo, path, start, end, max_commits=None, since=None):
    args = line_history_args(path, start, end, max_commits=max_commits, since=since)
    out = run_git(repo, args)
    return [l for l in out.split("\n") if _SHA_RE.match(l)]


def file_commit_count(repo, path, since=None):
    """Number of commits that touched `path`, following renames.

    Always passes `--follow`: without it, the count only includes commits
    that touched the file's *current* path, which undercounts a file that
    was ever renamed (see SKILL.md's own warning about this, and
    test_trace_cases.py::TestTwoRenames for the regression it guards).
    """
    args = ["log", "--format=%H", "--follow"]
    if since:
        args.append("--since=" + since)
    args.extend(["--", path])
    out = run_git(repo, args)
    return len([l for l in out.splitlines() if l.strip()])


def author_counts(repo, path):
    """Author name -> commit count for every commit that touched `path`,
    following renames (see `file_commit_count`'s docstring for why
    `--follow` is not optional here).

    Returns a plain dict, ordered by first appearance in `git log` output
    (i.e. most-recent-author-first among ties), not sorted by count;
    callers that want "top N authors" rank it themselves.
    """
    out = run_git(repo, ["log", "--format=%an", "--follow", "--", path])
    counts = {}
    for name in out.splitlines():
        name = name.strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts


def changed_paths(repo, sha):
    # -c core.quotepath=off: without it, git prints non-ASCII paths octal-
    # escaped and wrapped in double quotes (git's default core.quotepath is
    # true), which breaks self-exclusion comparisons and test-path detection
    # downstream and would show raw escaped garbage to the user. See
    # test_korean_paths.py for the fixture that pins this.
    out = run_git(repo, ["-c", "core.quotepath=off", "show", "--name-only",
                          "--format=", sha])
    return [p for p in out.splitlines() if p.strip()]


def grep_match_file_count(repo, token):
    """Count of files in the current working tree that contain `token`
    as a literal (fixed-string) match.

    This is used to judge whether a candidate pickaxe needle is too
    common in the tree today to be a distinctive signal, not to search
    history: `git grep` with no revision argument searches the working
    tree, which is exactly the "how common is this identifier right now"
    question needle selection needs answered.

    `git grep` exits 1, not 0, when nothing matches, unlike every other
    read subcommand this module wraps; that is a normal "zero files"
    result here, not a git failure, so it is tolerated explicitly rather
    than raising, the way a genuine nonzero exit from `grep` (a bad
    pattern, a repo with no HEAD yet) still does.
    """
    out = run_git(repo, ["grep", "-l", "-F", "-e", token], ok_returncodes=(0, 1))
    return len([line for line in out.splitlines() if line.strip()])


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
