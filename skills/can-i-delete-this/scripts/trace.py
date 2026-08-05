"""Run the archaeology strategy tree and emit facts as JSON.

This module makes no judgement calls. It gathers evidence; the agent
reading SKILL.md decides what the evidence means.
"""

import argparse
import json
import re

import gitq
import noise

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_\.]{3,}")


def _describe(repo, sha, why, cache):
    c, _ = _cached_meta_and_noise(repo, sha, cache)
    return {
        "sha": c.sha, "why": why, "subject": c.subject, "date": c.date,
        "author": c.author, "author_email": c.author_email,
        "files_changed": c.files_changed,
    }


def _cached_meta_and_noise(repo, sha, cache):
    """Memoize commit_meta + noise scoring per sha within one trace() call."""
    if sha in cache:
        return cache[sha]
    c = gitq.commit_meta(repo, sha)
    v = noise.score(
        c,
        whitespace_only=gitq.is_whitespace_only(repo, sha),
        paths=gitq.changed_paths(repo, sha),
    )
    cache[sha] = (c, v)
    return c, v


def _needles(repo, path, start, end):
    """Pick distinctive strings from the target lines to feed the pickaxe."""
    text = gitq.run_git(repo, ["show", "HEAD:" + path])
    lines = text.splitlines()[start - 1:end]
    found = []
    for line in lines:
        for token in _WORD.findall(line):
            if token not in found:
                found.append(token)
    return found[:5]


def trace(repo, path, start, end, *, max_commits=5000, since="5 years ago"):
    notes = []
    cache = {}
    blame_candidates = []
    blame_shas = gitq.blame_shas(repo, path, start, end)
    for sha in blame_shas:
        c, v = _cached_meta_and_noise(repo, sha, cache)
        blame_candidates.append({
            "sha": c.sha, "subject": c.subject, "date": c.date,
            "author": c.author,
            "noise": {"is_noise": v.is_noise, "category": v.category,
                      "confidence": v.confidence, "signals": list(v.signals)},
        })

    candidates = []
    seen = set()

    def add(sha, why):
        if sha in seen:
            return
        _, v = _cached_meta_and_noise(repo, sha, cache)
        if v.is_noise:
            return
        seen.add(sha)
        candidates.append(_describe(repo, sha, why, cache))

    for b in blame_candidates:
        if not b["noise"]["is_noise"]:
            add(b["sha"], "blame")

    if not candidates:
        notes.append("blame returned only noise commits; falling back to pickaxe")

    for needle in _needles(repo, path, start, end):
        for sha in gitq.pickaxe(repo, needle, max_commits=max_commits, since=since):
            add(sha, "pickaxe")

    try:
        for sha in gitq.line_history(repo, path, start, end):
            add(sha, "line-history")
    except RuntimeError as exc:
        notes.append("line history unavailable: {}".format(exc))

    candidates.sort(key=lambda c: c["date"])

    # A revert commit is not debris, it is the strongest do-not-delete
    # signal, so it must survive into the output even if some rule would
    # have filtered it out as noise. Collect it from the union of blame
    # candidates (all of them, noise or not) and accepted candidates,
    # rather than from the filtered candidate list alone.
    revert_chain = []
    for sha in seen | {b["sha"] for b in blame_candidates}:
        c, _ = _cached_meta_and_noise(repo, sha, cache)
        subject_lower = c.subject.lower()
        if subject_lower.startswith("revert") or "reapply" in subject_lower:
            revert_chain.append({
                "sha": c.sha, "subject": c.subject, "date": c.date,
                "author": c.author,
            })
    revert_chain.sort(key=lambda c: c["date"])

    co_changed = []
    if candidates:
        for p in gitq.changed_paths(repo, candidates[0]["sha"]):
            if p != path:
                co_changed.append({"path": p, "sha": candidates[0]["sha"]})

    total = len(gitq.run_git(repo, [
        "log", "--format=%H", "--max-count={}".format(max_commits + 1),
    ]).split())

    return {
        "target": {"path": path, "start": start, "end": end},
        "blame_candidates": blame_candidates,
        "introduction_candidates": candidates,
        "revert_chain": revert_chain,
        "co_changed": co_changed,
        "limits": {"max_commits": max_commits, "since": since,
                   "truncated": total > max_commits},
        "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser(description="Trace why a line of code exists.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--lines", required=True, help="START:END, e.g. 3:5")
    ap.add_argument("--max-commits", type=int, default=5000)
    ap.add_argument("--since", default="5 years ago")
    args = ap.parse_args()
    start, _, end = args.lines.partition(":")
    result = trace(
        args.repo, args.file, int(start), int(end or start),
        max_commits=args.max_commits, since=args.since,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
