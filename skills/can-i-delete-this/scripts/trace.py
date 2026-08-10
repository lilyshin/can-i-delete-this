"""Run the archaeology strategy tree and emit facts as JSON.

This module makes no judgement calls. It gathers evidence; the agent
reading SKILL.md decides what the evidence means.
"""

import argparse
import json
import re
import sys

import gitq
import noise

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_\.]{3,}")

# Heuristic denylist of language keywords and ubiquitous programming tokens
# that make poor pickaxe needles precisely because they are everywhere: a
# `git log -S` match on one of these says nothing about which commit is
# distinctive. This is not a lexer and is not exhaustive; it is a curated
# list spanning a handful of common languages (Python, Ruby, Elixir,
# JS/TS, Java/Kotlin/C-family) that this project's own fixtures and
# real-world traces surfaced as noisy. Comparison against it is
# case-insensitive (see _rank_needles), so it also catches `True`/`None`
# style capitalized keywords.
_STOPWORDS = frozenset({
    "def", "return", "import", "from", "self", "this", "class", "function",
    "const", "public", "private", "static", "void", "end", "module",
    "defmodule", "defp", "when", "case", "cond", "else", "elif", "true",
    "false", "nil", "null", "none", "let", "var", "new", "async", "await",
    "print", "raise", "rescue", "try", "catch", "except", "finally",
    "with", "yield", "lambda", "while", "for", "break", "continue", "pass",
    "global", "nonlocal", "if", "do", "then", "begin", "override",
    "extends", "implements", "interface", "package", "namespace", "using",
    "include", "require", "super", "instanceof", "throws", "throw",
})

# A token found in more than this many files of the current working tree
# is common enough that matching it tells you little; see _select_needles.
_COMMON_TOKEN_FILE_THRESHOLD = 15

# Rarity-probing a token costs one `git grep` call, so only the top-ranked
# tokens get checked, bounding the cost regardless of how many distinct
# tokens the target lines contain.
_RARITY_PROBE_LIMIT = 8

# At most this many needles run path-scoped (see trace()); repo-wide runs
# on the rarest _REPO_WIDE_NEEDLE_LIMIT of those, since repo-wide search is
# the expensive, junk-prone half of pickaxe.
_PATH_SCOPED_NEEDLE_LIMIT = 3
_REPO_WIDE_NEEDLE_LIMIT = 2


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


def _tokens_from_target(repo, path, start, end):
    """Every distinct token on the target lines, in first-seen order."""
    text = gitq.run_git(repo, ["show", "HEAD:" + path])
    lines = text.splitlines()[start - 1:end]
    found = []
    for line in lines:
        for token in _WORD.findall(line):
            if token not in found:
                found.append(token)
    return found


def _rank_needles(tokens):
    """Order candidate needle tokens best-first.

    Longer tokens, and tokens containing `_` or `.`, look like real
    identifiers rather than generic prose words, so they make more
    distinctive pickaxe needles. `sorted` is stable, so tokens that tie on
    both measures keep their original (first-seen) relative order.
    """
    def rank_key(token):
        looks_like_identifier = "_" in token or "." in token
        return (looks_like_identifier, len(token))
    return sorted(tokens, key=rank_key, reverse=True)


def _select_needles(repo, path, start, end):
    """Pick pickaxe needles from the target lines' current content.

    Returns (path_needles, repo_needles, notes):

    - path_needles: up to `_PATH_SCOPED_NEEDLE_LIMIT` tokens for a
      path-scoped pickaxe search.
    - repo_needles: up to `_REPO_WIDE_NEEDLE_LIMIT` tokens (the rarest of
      path_needles) for a repo-wide pickaxe search, since repo-wide is the
      expensive, junk-prone half of the search.
    - notes: zero or more human-readable strings disclosing a deviation
      worth knowing about (tokens rejected as too common, a narrower
      repo-wide needle set, or a stopword-fallback).

    Selection: drop stopwords, rank the rest (see _rank_needles), then
    verify rarity for the top `_RARITY_PROBE_LIMIT` ranked tokens with
    `gitq.grep_match_file_count` against the current working tree; a token
    found in more than `_COMMON_TOKEN_FILE_THRESHOLD` files is
    deprioritized (moved after the un-probed tail) rather than dropped, so
    it is still available if nothing better exists. If every token on the
    target lines is a stopword, this falls back to the pre-ranking
    behavior (first tokens found, unfiltered) rather than returning no
    needles at all, and says so in `notes`.
    """
    all_tokens = _tokens_from_target(repo, path, start, end)
    notes = []

    candidates = [t for t in all_tokens if t.lower() not in _STOPWORDS]
    if not candidates:
        notes.append(
            "needle selection: every token on the target lines is a "
            "stopword (a language keyword or an ubiquitous programming "
            "term); falling back to the first tokens found, unranked"
        )
        fallback = all_tokens[:5]
        return (fallback[:_PATH_SCOPED_NEEDLE_LIMIT],
                fallback[:_REPO_WIDE_NEEDLE_LIMIT], notes)

    ranked = _rank_needles(candidates)
    probe_pool = ranked[:_RARITY_PROBE_LIMIT]
    rare, common = [], []
    for token in probe_pool:
        try:
            file_count = gitq.grep_match_file_count(repo, token)
        except RuntimeError:
            # A grep failure should not sink needle selection; keep the
            # token in its ranked position rather than discarding it.
            rare.append(token)
            continue
        if file_count > _COMMON_TOKEN_FILE_THRESHOLD:
            common.append(token)
        else:
            rare.append(token)
    # Tokens past the probe limit were never rarity-checked (bounded
    # cost); keep them ranked, after the confirmed-rare ones and before
    # the confirmed-common ones.
    ordered = rare + ranked[_RARITY_PROBE_LIMIT:] + common

    if common:
        notes.append(
            "needle selection: deprioritized {} common token(s) found in "
            "more than {} files of the current tree: {}".format(
                len(common), _COMMON_TOKEN_FILE_THRESHOLD,
                ", ".join(common))
        )

    path_needles = ordered[:_PATH_SCOPED_NEEDLE_LIMIT]
    repo_needles = ordered[:_REPO_WIDE_NEEDLE_LIMIT]
    if len(path_needles) > len(repo_needles):
        notes.append(
            "needle selection: repo-wide pickaxe used only the rarest {} "
            "of {} path-scoped needle(s) ({}), to bound repo-wide search "
            "cost".format(len(repo_needles), len(path_needles),
                          ", ".join(repo_needles))
        )
    return path_needles, repo_needles, notes


def trace(repo, path, start, end, *, max_commits=5000, since=None,
          max_candidates=200, include_commits=None):
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
    # Every sha touched by any search path (blame, pickaxe, line-history),
    # regardless of noise verdict or the candidate cap below. revert_chain
    # is built from this, not from `candidates`, because a revert commit
    # must survive even when noise-filtered or capped out.
    encountered = set(blame_shas)
    cap_state = {"hit": False}

    def add(sha, why):
        encountered.add(sha)
        if sha in seen:
            return
        _, v = _cached_meta_and_noise(repo, sha, cache)
        if v.is_noise:
            return
        # Blame candidates are few and the most important clue, so they
        # are exempt from the total-candidate cap; only pickaxe/line-history
        # additions can be capped.
        if why != "blame" and len(candidates) >= max_candidates:
            cap_state["hit"] = True
            return
        seen.add(sha)
        candidates.append(_describe(repo, sha, why, cache))

    for b in blame_candidates:
        if not b["noise"]["is_noise"]:
            add(b["sha"], "blame")

    if not candidates:
        notes.append("blame returned only noise commits; falling back to pickaxe")

    # Path-scoped pickaxe first, on up to three ranked needles: cheap, and
    # it finds anything that shares the target lines' current path with
    # its introducing commit. Repo-wide second, narrower (the rarest one
    # or two needles only): it is what crosses renames and cross-file
    # moves (a needle drawn from the target lines can find the commit that
    # introduced them under a different path or file entirely), but it is
    # also the expensive, junk-prone half of the search, since it walks
    # every commit that ever changed the needle's occurrence count
    # anywhere in the repository. Repo-wide must never be skipped just
    # because path-scoped already found something: a commit found
    # path-scoped is not evidence that nothing needed a repo-wide search
    # too (see the module-level note on cross-file moves).
    path_needles, repo_needles, needle_notes = _select_needles(repo, path, start, end)
    notes.extend(needle_notes)

    for needle in path_needles:
        for sha in gitq.pickaxe(repo, needle, path=path, max_commits=max_commits, since=since):
            add(sha, "pickaxe")

    for needle in repo_needles:
        for sha in gitq.pickaxe(repo, needle, max_commits=max_commits, since=since):
            add(sha, "pickaxe")

    try:
        for sha in gitq.line_history(repo, path, start, end,
                                     max_commits=max_commits, since=since):
            add(sha, "line-history")
    except RuntimeError as exc:
        notes.append("line history unavailable: {}".format(exc))

    # A commit an agent names explicitly (SKILL.md's short-history path,
    # where `git log -p --follow` surfaced a commit that blame, pickaxe and
    # line-history above never touched at all, most often a rename bundling
    # enough unrelated change to defeat blame's own move detection). This is
    # the one place facts are allowed to originate from something other than
    # this function's own git searches, but the fact itself still has to
    # come from git: `_cached_meta_and_noise` below calls `gitq.commit_meta`,
    # which fails loudly on a sha that does not exist in this repository, so
    # a fabricated or mistyped sha is rejected here, recorded in `notes`, and
    # never becomes a candidate. It is deliberately not routed through
    # `add()`: unlike a blame/pickaxe/line-history hit, an explicitly named
    # commit is never noise-filtered out (SKILL.md's own workflow already
    # asks agents to cite a noise-flagged N10 squash commit when its diff,
    # not its message, is what actually introduced the target lines, and a
    # commit an agent points at by name deserves the same trust), and it is
    # exempt from the candidate cap for the same reason blame is: naming one
    # specific commit is a deliberate, bounded addition, not the kind of
    # unbounded search result the cap exists to bound.
    for raw_sha in include_commits or ():
        candidate_sha = (raw_sha or "").strip()
        if not candidate_sha:
            continue
        try:
            c, _ = _cached_meta_and_noise(repo, candidate_sha, cache)
        except RuntimeError as exc:
            notes.append(
                "cited commit {!r} not found in this repository; ignored: {}"
                .format(candidate_sha, exc)
            )
            continue
        encountered.add(c.sha)
        if c.sha in seen:
            continue
        seen.add(c.sha)
        candidates.append(_describe(repo, c.sha, "cited", cache))

    candidates.sort(key=lambda c: c["date"])

    if cap_state["hit"]:
        notes.append(
            "introduction candidate cap ({}) reached; some pickaxe/"
            "line-history candidates were not recorded".format(max_candidates)
        )

    # A revert commit is not debris, it is the strongest do-not-delete
    # signal, so it must survive into the output even if some rule would
    # have filtered it out as noise, or the candidate cap would have
    # dropped it. Collect it from every sha encountered along any search
    # path, noise or not, capped or not.
    revert_chain = []
    for sha in encountered:
        c, _ = _cached_meta_and_noise(repo, sha, cache)
        subject_lower = c.subject.lower()
        if (subject_lower.startswith("revert") or "reapply" in subject_lower
                or "reintroduce" in subject_lower):
            revert_chain.append({
                "sha": c.sha, "subject": c.subject, "date": c.date,
                "author": c.author,
            })
    revert_chain.sort(key=lambda c: c["date"])

    # co_changed cannot be computed against "the" introducing commit here:
    # candidates is sorted chronologically (oldest first), not by which one
    # actually introduced the target lines -- trace.py has no way to know
    # that, since the verdict deciding it is written after the tracer runs.
    # So gather co-changes across every introduction candidate, tagging each
    # entry with the sha it came from; render.py and artifacts.py can then
    # filter down to the sha the verdict actually cites as real.
    co_changed = []
    seen_co_changed = set()
    for cand in candidates:
        for p in gitq.changed_paths(repo, cand["sha"]):
            if p != path:
                key = (cand["sha"], p)
                if key not in seen_co_changed:
                    seen_co_changed.add(key)
                    co_changed.append({"path": p, "sha": cand["sha"]})

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
                   "truncated": total > max_commits,
                   "max_candidates": max_candidates,
                   "candidate_cap_reached": cap_state["hit"]},
        "notes": notes,
    }


def _parse_lines(spec):
    """Parse "--lines START:END" (or "START") into a pair of ints.

    Raises ValueError with a message naming the bad input, which main()
    turns into a clean CLI error instead of a raw traceback.
    """
    start_str, _, end_str = spec.partition(":")
    try:
        start = int(start_str)
        end = int(end_str) if end_str else start
    except ValueError:
        raise ValueError(
            "--lines must be START or START:END with integer values, got {!r}"
            .format(spec)
        )
    return start, end


def main():
    ap = argparse.ArgumentParser(description="Trace why a line of code exists.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--lines", required=True, help="START:END, e.g. 3:5")
    ap.add_argument("--max-commits", type=int, default=5000)
    ap.add_argument("--since", default=None,
                     help="e.g. '3 years ago'; unset means no time bound")
    ap.add_argument("--max-candidates", type=int, default=200)
    ap.add_argument(
        "--include-commit", action="append", dest="include_commits",
        default=None, metavar="SHA",
        help="add SHA to introduction_candidates (why: 'cited'), verified "
             "against this repository's own history; repeatable. For a "
             "commit an agent found by reading history directly that blame, "
             "pickaxe and line-history did not surface on their own.",
    )
    args = ap.parse_args()

    try:
        start, end = _parse_lines(args.lines)
    except ValueError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        sys.exit(2)

    # gitq.run_git raises RuntimeError when the underlying git command
    # fails (a nonexistent path, a line range past the end of the file,
    # and similar bad-input cases all surface this way). GitWriteAttempt is
    # also a RuntimeError but signals a bug in this project's own code, not
    # bad user input, so it is deliberately let through uncaught rather than
    # folded into the same clean-error handling as a real git failure.
    try:
        result = trace(
            args.repo, args.file, start, end,
            max_commits=args.max_commits, since=args.since,
            max_candidates=args.max_candidates,
            include_commits=args.include_commits,
        )
    except gitq.GitWriteAttempt:
        raise
    except RuntimeError as exc:
        print("error: could not trace {}:{}: {}".format(args.file, args.lines, exc),
              file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
