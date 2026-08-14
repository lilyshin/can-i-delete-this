"""Scan a path for commented-out code and attach the facts behind each block.

Makes no judgement call. There is no grade in this module's output and no
word like "safe" anywhere in it: the scan says "here is a block, and here
is the commit that commented it out". Grading a candidate means running
`trace.py` on it and writing a verdict, which is what SKILL.md's workflow
already does one target at a time.

The split mirrors the rest of this project: `scanner.py` decides what a
block is and never touches git, this module talks to git through `gitq`
and never decides what a block is.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import gitq
import noise
import scanner

# A file whose HEAD content is larger than this is skipped rather than
# scanned. Counted in `limits`, never silently dropped.
MAX_FILE_BYTES = 400000

# Vocabulary that marks a commenting-out commit worth reading first. This
# is an ordering hint, not a filter and not a grade: it never excludes a
# candidate, and per the 0.7.0 doctrine on subjects, an agent reads the
# subject and body itself and decides. Korean terms are included because
# the repositories this was built for write Korean commit messages.
_LOOK_FIRST_WORDS = (
    "revert", "reverted", "hotfix", "incident", "outage", "rollback",
    "roll back", "disable", "disabled", "temporar", "workaround",
    "장애", "임시", "롤백", "되돌", "긴급", "비활성",
)


def _looks_urgent(commit):
    haystack = ((commit.get("subject") or "") + "\n"
                + (commit.get("body") or "")).lower()
    return any(word in haystack for word in _LOOK_FIRST_WORDS)


def _skip_reason(path):
    """Why this path is not scanned, or None when it is."""
    if any(marker in path for marker in noise._VENDOR_DIRS):
        return "vendored"
    if any(hint in path for hint in noise._GENERATED_HINTS):
        return "generated"
    if scanner.marker_for(path) is None:
        return "unsupported"
    return None


def _age_days(iso_date, now):
    try:
        when = datetime.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when).days


# Same cap and reasoning as trace.py's `_BODY_LIMIT`: the body is where
# intent lives, and it is unbounded upstream (measured on a real
# repository: median 280 characters, maximum 3725).
_BODY_LIMIT = 600


def _commit_facts(repo, sha, now, cache):
    """The commenting-out commit's own facts, read from git.

    Cached per sha: one commit often comments out several blocks, and
    `commit_meta` is the most expensive call in this module.
    """
    if sha in cache:
        return cache[sha]
    commit = gitq.commit_meta(repo, sha)
    body = commit.body or ""
    truncated = len(body) > _BODY_LIMIT
    facts = {
        "sha": commit.sha,
        "subject": commit.subject,
        "body": body[:_BODY_LIMIT] if truncated else body,
        "body_truncated": truncated,
        "author": commit.author,
        "author_email": commit.author_email,
        "date": commit.date,
        "age_days": _age_days(commit.date, now),
        "files_changed": commit.files_changed,
        "hints": list(noise.score(
            commit,
            whitespace_only=gitq.is_whitespace_only(repo, sha),
            paths=gitq.changed_paths(repo, sha),
        ).hints),
    }
    cache[sha] = facts
    return facts


def _oldest(repo, shas, now, cache):
    """The oldest commit among a block's blame shas, and how many there were.

    A block can carry more than one sha: a later commit may have touched
    one of its commented lines, or two adjacent blocks may have merged into
    one run. The oldest is the commit that started the block's life, which
    is the fact "how long has this been sitting here" is measured from.
    """
    facts = [_commit_facts(repo, sha, now, cache) for sha in shas]
    facts.sort(key=lambda f: f["date"] or "")
    return facts[0], len(facts)


def scan(repo, path, *, min_lines=None, max_candidates=200, now=None):
    """Find commented-out code blocks under `path` and attach commit facts."""
    if now is None:
        now = datetime.now(timezone.utc)
    if min_lines is None:
        min_lines = scanner.MIN_BLOCK_LINES

    notes = ["block comments (/* ... */) are not detected; only line comments"]
    counts = {"scanned": 0, "unsupported": 0, "vendored": 0, "generated": 0,
              "too_large": 0, "missing_at_head": 0}
    candidates = []
    cache = {}
    cap_reached = False

    listed = gitq.run_git(repo, ["ls-files", "--", path])
    files = [line for line in listed.splitlines() if line.strip()]

    for file_path in files:
        reason = _skip_reason(file_path)
        if reason:
            counts[reason] += 1
            continue
        try:
            text = gitq.run_git(repo, ["show", "HEAD:" + file_path])
        except RuntimeError:
            counts["missing_at_head"] += 1
            continue
        if len(text) > MAX_FILE_BYTES:
            counts["too_large"] += 1
            continue
        counts["scanned"] += 1
        marker = scanner.marker_for(file_path)
        for block in scanner.find_blocks(text, marker, min_lines=min_lines):
            if len(candidates) >= max_candidates:
                cap_reached = True
                break
            try:
                shas = gitq.blame_shas(repo, file_path, block.start, block.end)
            except RuntimeError:
                shas = []
            if shas:
                commit, touched = _oldest(repo, shas, now, cache)
            else:
                commit, touched = None, 0
                notes.append(
                    "blame failed for {}:{}-{}; the block is reported "
                    "without its commit".format(
                        file_path, block.start, block.end))
            candidates.append({
                "path": file_path,
                "start": block.start,
                "end": block.end,
                "lines": block.lines,
                "code_lines": block.code_lines,
                "commented_out_by": commit,
                "touched_by_commits": touched,
                "look_first": bool(commit) and _looks_urgent(commit),
            })
        if cap_reached:
            break

    # Oldest first. A candidate with no commit facts sorts last rather than
    # first: an unknown date is not evidence of age.
    candidates.sort(key=lambda c: (
        c["commented_out_by"] is None,
        (c["commented_out_by"] or {}).get("date") or "",
        c["path"], c["start"]))

    if counts["too_large"]:
        notes.append("{} file(s) over {} bytes were skipped".format(
            counts["too_large"], MAX_FILE_BYTES))
    if counts["missing_at_head"]:
        notes.append("{} tracked file(s) are not present at HEAD".format(
            counts["missing_at_head"]))

    return {
        "target": {"repo": repo, "path": path},
        "candidates": candidates,
        "limits": {
            "files_scanned": counts["scanned"],
            "files_skipped_unsupported": counts["unsupported"],
            "files_skipped_vendored": counts["vendored"],
            "files_skipped_generated": counts["generated"],
            "min_lines": min_lines,
            "max_candidates": max_candidates,
            "candidate_cap_reached": cap_reached,
        },
        "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Scan a path for commented-out code. Finds candidates "
                    "and the commit behind each one; grades nothing.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--path", default=".",
                     help="directory or file to scan, relative to the repo")
    ap.add_argument("--min-lines", type=int, default=None,
                     help="shortest comment run to report (default {})".format(
                         scanner.MIN_BLOCK_LINES))
    ap.add_argument("--max-candidates", type=int, default=200)
    args = ap.parse_args()

    try:
        result = scan(args.repo, args.path, min_lines=args.min_lines,
                      max_candidates=args.max_candidates)
    except gitq.GitWriteAttempt:
        raise
    except RuntimeError as exc:
        print("error: could not scan {}: {}".format(args.path, exc),
              file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
