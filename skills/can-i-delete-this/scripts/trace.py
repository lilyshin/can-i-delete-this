"""Run the archaeology strategy tree and emit facts as JSON.

This module makes no judgement calls. It gathers evidence; the agent
reading SKILL.md decides what the evidence means.
"""

import argparse
import json
import posixpath
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

# Lines of context shown on each side of the target range in the report's
# code snippet. Chosen to be enough to orient a reader without an editor
# open, while staying short enough not to crowd the verdict block it
# renders directly under (see render.py).
_SNIPPET_CONTEXT = 4

# How many of a file's authors (by commit count, across its whole
# --follow'd history) the report names as "main authors".
_TOP_AUTHORS_LIMIT = 3

# How far back "commits touched this file in the last year" looks. A
# literal string, not a timedelta, because it is handed straight to
# `git log --since`.
_ACTIVITY_WINDOW = "1 year ago"

# Characters of commit body carried per candidate. The body is where intent
# usually lives (a subject like `fix: guard charge` grades nothing), and
# `gitq.commit_meta` already reads it, so passing it on costs no git call.
# It is capped because it is unbounded upstream and a capped trace holds up
# to `max_candidates` of them: measured over 60 commits of a real
# 20,000-commit repository, bodies ran to a median of 280 characters and a
# maximum of 3,725, so 600 carries most messages whole while keeping the
# worst case off the agent's context. A cut body is disclosed with
# `body_truncated`, since an agent that believes it read the whole message
# would stop looking.
_BODY_LIMIT = 600

# How many co-changed paths trace() keeps per introduction candidate. A
# commit touching hundreds of files (a vendor bump, a monorepo-wide rename)
# would otherwise dump its entire file list into co_changed and dominate the
# whole JSON payload for one candidate's worth of evidence; measured against
# a real repository, a single such commit made co_changed the largest field
# in the trace by a wide margin. What survives the cut is picked, not
# truncated blindly: co_changed_totals in trace()'s return records the true
# per-commit count so the cut is disclosed rather than made to look like a
# complete list.
#
# 20, not 5: measured against a real 200-candidate trace, a cap of 5
# truncated 124 of the 200 candidate commits (62%); a cap of 20 truncates
# only 34 (17%). The per-commit path-count distribution behind that
# (5-or-fewer: 76 commits, 6-20: 90, 21-100: 31, over 100: 3) shows most
# commits' own co-changes fit in 20 without help from the priority
# ordering at all, so 20 keeps far more commits whole while still bounding
# the pathological ones.
CO_CHANGED_PER_COMMIT = 20


def _body_fields(commit):
    body = commit.body or ""
    if len(body) > _BODY_LIMIT:
        return {"body": body[:_BODY_LIMIT], "body_truncated": True}
    return {"body": body, "body_truncated": False}


def _describe(repo, sha, why, cache):
    c, v = _cached_meta_and_noise(repo, sha, cache)
    out = {
        "sha": c.sha, "why": why, "subject": c.subject, "date": c.date,
        "author": c.author, "author_email": c.author_email,
        "files_changed": c.files_changed,
        # Vocabulary the subject matched. A candidate is here *because* no
        # signal filtered it, so `signals` would be empty by construction
        # and is not carried; `hints` are the part still worth reading, and
        # SKILL.md rule 7 is what tells an agent how much they are worth.
        # Free to include: the verdict is already computed and cached.
        "hints": list(v.hints),
    }
    out.update(_body_fields(c))
    return out


class _ScoreCache(dict):
    """Memoizes commit_meta + noise scoring per sha within one trace()
    call, and carries the target path every scoring decision is made
    against.

    The path lives on the cache rather than travelling as an argument
    through all eight call sites for a reason: the cosmetic check is
    path-scoped, so if some callers passed a path and others did not, the
    verdict a sha got would depend on which code path reached it first
    and then be reused by everyone else.
    """

    def __init__(self, path=None):
        super().__init__()
        self.path = path


def _cached_meta_and_noise(repo, sha, cache):
    """Memoize commit_meta + noise scoring per sha within one trace() call."""
    if sha in cache:
        return cache[sha]
    c = gitq.commit_meta(repo, sha)
    path = getattr(cache, "path", None)
    v = noise.score(
        c,
        whitespace_only=gitq.is_whitespace_only(repo, sha),
        paths=gitq.changed_paths(repo, sha),
        diff_lines=gitq.diff_lines(repo, sha, path) if path else None,
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


def _read_snippet_source(repo, path):
    """The target file's content at HEAD, or why it could not be read.

    Deliberately separate from `_tokens_from_target`, which reads the same
    `git show HEAD:<path>` shape for needle selection but is allowed to let
    a RuntimeError propagate (a missing path there aborts the whole trace,
    existing, unchanged behavior). The snippet is a lower-stakes addition
    to the report -- it must degrade to a short explanation instead of
    taking the rest of the trace down with it -- so it catches the same
    failure here instead of raising.

    Returns (text, reason). `reason` is None on success, or one of
    "missing-at-head" / "binary" / "irregular-line-break".

    Reads through `gitq.run_git_bytes`, not `gitq.run_git`: `run_git`'s
    text mode runs Python's universal-newline translation, which silently
    rewrites a lone "\\r" to "\\n" before this function -- or
    `gitq.has_splitlines_divergence` below -- ever sees it, so a real
    divergence between `str.splitlines()` and `patch.py`'s "\\n"-only
    split would already have been erased by the time it could be
    detected. Decoding the raw bytes ourselves is what lets that
    detection see what git actually stored (see `gitq.run_git_bytes`'s
    docstring, and `patch.py`'s `_read_working_tree`, which reads the
    working tree side of the same comparison the identical way, through
    `open(..., "rb")` rather than text mode).
    """
    try:
        raw = gitq.run_git_bytes(repo, ["show", "HEAD:" + path])
    except RuntimeError:
        return None, "missing-at-head"
    if b"\x00" in raw:
        # git's own convention: a NUL byte means binary. Checked on the
        # raw bytes, before decoding, the same order patch.py's
        # `_read_working_tree` uses for the same reason: a NUL byte is a
        # binary signal regardless of whether the rest of the file
        # happens to decode as valid UTF-8.
        return None, "binary"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "binary"
    if gitq.has_splitlines_divergence(text):
        # `str.splitlines()` (used two lines below, and by `patch.py`'s
        # own line-number check against the working tree) breaks on any
        # of `gitq`'s `_SPLITLINES_ONLY_BREAKS` or a lone "\r", none of which
        # `patch.py`'s "\n"-only split treats as a break at all. The two
        # counts disagree on such a file, so any line number this function
        # would otherwise record cannot be trusted -- not just near the
        # divergent character itself, since a single extra line shifts
        # every recorded number after it. Marking the snippet unavailable
        # here, rather than leaving the mismatch for patch.py's
        # `_check_unmoved` to maybe catch, refuses regardless of how far
        # the divergence sits from the target: `_check_unmoved` only ever
        # compares the lines inside the recorded snippet window, and a
        # divergent character positioned far enough past that window (or
        # inside a run of identical lines) can leave the miscounted lines
        # matching by coincidence, letting a patch build against numbers
        # that are already wrong.
        return None, "irregular-line-break"
    return text, None


def _compute_snippet(repo, path, start, end, context=_SNIPPET_CONTEXT):
    """The target lines plus a few lines of surrounding context, read from
    HEAD, for the report to show directly under the verdict.

    Never raises: a missing path, an out-of-range line range, binary
    content, or a character that would make `str.splitlines()` number the
    file differently from `patch.py` (see `gitq.has_splitlines_divergence`)
    all come back as `{"available": False, "reason": ...}` so render.py
    can say so briefly instead of crashing or showing an empty box (see
    render.py's `_snippet_html`).
    """
    text, reason = _read_snippet_source(repo, path)
    if reason:
        return {"available": False, "reason": reason}
    lines = text.splitlines()
    total = len(lines)
    if start < 1 or start > total:
        return {"available": False, "reason": "out-of-range"}
    # A target end past the last line is clamped rather than treated as
    # out-of-range outright: the range still starts inside the file, so
    # showing what exists (up to `total`) is more useful than refusing
    # to show anything at all.
    target_end = min(end, total) if end >= start else start
    ctx_start = max(1, start - context)
    ctx_end = min(total, target_end + context)
    return {
        "available": True,
        "start_line": ctx_start,
        "end_line": ctx_end,
        "target_start": start,
        "target_end": target_end,
        "lines": lines[ctx_start - 1:ctx_end],
    }


def _file_last_touch(repo, path, cache):
    """Fallback "last touched" when line-history is unavailable: the most
    recent commit that touched the whole file, following renames.
    """
    try:
        out = gitq.run_git(repo, ["log", "-1", "--format=%H", "--follow", "--", path])
    except RuntimeError:
        return None
    sha = out.strip()
    if not sha:
        return None
    c, _ = _cached_meta_and_noise(repo, sha, cache)
    return {"sha": c.sha, "date": c.date, "scope": "file"}


def _compute_activity(repo, path, line_history_shas, cache):
    """Recency and ownership signals for the report's History card: when
    the target lines (or, failing that, the file) were last touched, how
    many commits touched the file in the last year, and its main authors
    by commit count. This is the strongest deterministic "is this dead"
    signal the tracer can offer, which is exactly what the tool is for.

    Each fact degrades independently (None / [] / omitted key) rather than
    taking the whole trace down: none of these are essential to the
    strategy tree's own verdict-relevant evidence, so a git failure here
    (a shallow clone missing history, an exotic path) must not turn into a
    crash for the rest of trace().

    `line_history_shas` is git log's own order for `-L start,end:path`,
    which is newest-first by default, so its first element -- if the
    caller's line-history search succeeded at all -- is already the most
    recent commit to touch the exact target lines, at no extra git call.
    """
    if line_history_shas:
        sha = line_history_shas[0]
        c, _ = _cached_meta_and_noise(repo, sha, cache)
        last_touch = {"sha": c.sha, "date": c.date, "scope": "lines"}
    else:
        last_touch = _file_last_touch(repo, path, cache)

    try:
        commits_last_year = gitq.file_commit_count(repo, path, since=_ACTIVITY_WINDOW)
    except RuntimeError:
        commits_last_year = None

    try:
        counts = gitq.author_counts(repo, path)
    except RuntimeError:
        counts = {}
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    top_authors = [{"name": name, "count": count}
                    for name, count in ranked[:_TOP_AUTHORS_LIMIT]]

    return {
        "last_touch": last_touch,
        "commits_last_year": commits_last_year,
        "top_authors": top_authors,
    }


def _co_changed_priority(co_changed_path, target_dirname):
    """Rank key for one commit's co-changed paths, best-first.

    Test paths (noise.is_test_path) outrank everything: a co-changed test is
    the strongest available signal of what guards the target, and must not
    be pushed out of the cap by an unrelated file just because that file
    happened to be touched too. Paths in the target's own directory outrank
    the rest next, on the theory that a neighbor changed in the same commit
    is more likely to be related to the target than something in a distant
    part of the tree. Everything else shares the lowest rank.

    Returns an int, not a bool, because there are three tiers, not two.
    `sorted` is stable, so paths tying on this key keep the relative order
    git itself reported them in; this function only ever reorders across
    tiers, never within one, so it cannot manufacture an ordering fact git
    did not give it.

    `posixpath.dirname`, not `os.path.dirname`: every path here (both
    `co_changed_path` and `target_dirname`) is a path git reported, and git
    always reports paths POSIX-style, forward slashes only, regardless of
    the OS this runs on. `os.path.dirname` would be `ntpath.dirname` on
    Windows, which happens to also split on `/` so the two never actually
    disagreed in practice, but `posixpath` says why on its face instead of
    relying on that coincidence, matching noise.is_test_path's own
    `posixpath.split` and every other path-shaped comparison in trace().
    """
    if noise.is_test_path(co_changed_path):
        return 0
    if posixpath.dirname(co_changed_path) == target_dirname:
        return 1
    return 2


def trace(repo, path, start, end, *, max_commits=5000, since=None,
          max_candidates=200, include_commits=None,
          max_co_changed=CO_CHANGED_PER_COMMIT):
    # Normalized once, at the door, so a caller-supplied "./billing/x.py"
    # behaves identically to the bare "billing/x.py" for everything below:
    # gitq.changed_paths never returns a leading "./" (git doesn't emit
    # one), so an un-normalized path would fail the `p != path`
    # self-exclusion later in this function (letting the target sneak into
    # its own co_changed and eat a cap slot a real co-changed path should
    # have had) and would never equal the same-directory tier's
    # target_dirname ("./billing" from os.path.dirname("./billing/x.py")
    # never equals git's own "billing"), silently collapsing that tier to
    # dead code for the rest of this call. posixpath.normpath, not
    # os.path.normpath, for the same POSIX-paths-from-git reason
    # _co_changed_priority's docstring gives.
    path = posixpath.normpath(path)
    notes = []
    cache = _ScoreCache(path)
    blame_candidates = []
    blame_shas = gitq.blame_shas(repo, path, start, end)
    for sha in blame_shas:
        c, v = _cached_meta_and_noise(repo, sha, cache)
        entry = {
            "sha": c.sha, "subject": c.subject, "date": c.date,
            "author": c.author,
            "noise": {"is_noise": v.is_noise, "category": v.category,
                      "confidence": v.confidence, "signals": list(v.signals),
                      "hints": list(v.hints)},
        }
        entry.update(_body_fields(c))
        blame_candidates.append(entry)

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

    # `commands` records the actual argv of every git search this trace
    # ran, in the order it ran them, so the report's reproduction-commands
    # section (render.py's `_repro_html`) can show a skeptical reader the
    # real invocations instead of an idealized rewrite. A needle or search
    # that never ran (an empty needle list, a line-history failure) simply
    # never gets an entry here -- see each append site below for why.
    commands = [{"kind": "blame", "args": gitq.blame_args(path, start, end)}]

    for needle in path_needles:
        commands.append({
            "kind": "pickaxe", "scope": "path", "needle": needle,
            "args": gitq.pickaxe_args(needle, path=path, max_commits=max_commits, since=since),
        })
        for sha in gitq.pickaxe(repo, needle, path=path, max_commits=max_commits, since=since):
            add(sha, "pickaxe")

    for needle in repo_needles:
        commands.append({
            "kind": "pickaxe", "scope": "repo", "needle": needle,
            "args": gitq.pickaxe_args(needle, max_commits=max_commits, since=since),
        })
        for sha in gitq.pickaxe(repo, needle, max_commits=max_commits, since=since):
            add(sha, "pickaxe")

    line_history_shas = []
    try:
        line_history_shas = gitq.line_history(repo, path, start, end,
                                              max_commits=max_commits, since=since)
    except RuntimeError as exc:
        # No entry appended to `commands`: this search did not actually
        # produce a result, so a reproduction command for it would not
        # "match what the code actually ran" (it would just fail again).
        notes.append("line history unavailable: {}".format(exc))
    else:
        commands.append({
            "kind": "line-history",
            "args": gitq.line_history_args(path, start, end,
                                            max_commits=max_commits, since=since),
        })
    for sha in line_history_shas:
        add(sha, "line-history")

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
    # asks agents to cite a noise-flagged commit when its diff,
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
    #
    # A commit can touch far more paths than are worth carrying (a vendor
    # bump, a monorepo-wide rename), so only the top `max_co_changed` of
    # each commit's paths survive into `co_changed`, ranked by
    # `_co_changed_priority` (tests first, then the target's own directory,
    # then everything else) and otherwise left in git's own order. The true
    # per-commit count -- before that cut -- is recorded in
    # `co_changed_totals`, keyed by sha, so a cut is disclosed rather than
    # made to look like a complete list.
    co_changed = []
    co_changed_totals = {}
    seen_co_changed = set()
    target_dirname = posixpath.dirname(path)
    for cand in candidates:
        sha = cand["sha"]
        changed = [p for p in gitq.changed_paths(repo, sha) if p != path]
        co_changed_totals[sha] = len(changed)
        ranked = sorted(changed, key=lambda p: _co_changed_priority(p, target_dirname))
        for p in ranked[:max_co_changed]:
            key = (sha, p)
            if key not in seen_co_changed:
                seen_co_changed.add(key)
                co_changed.append({"path": p, "sha": sha})

    total = len(gitq.run_git(repo, [
        "log", "--format=%H", "--max-count={}".format(max_commits + 1),
    ]).split())

    # snippet and activity are both report-facing additions, not evidence
    # the strategy tree reasons about, so neither is allowed to take the
    # rest of trace() down with it: _compute_snippet never raises on its
    # own (see its docstring), and _compute_activity degrades each of its
    # three facts independently.
    snippet = _compute_snippet(repo, path, start, end)
    activity = _compute_activity(repo, path, line_history_shas, cache)

    return {
        "target": {"path": path, "start": start, "end": end},
        "repo": repo,
        "blame_candidates": blame_candidates,
        "introduction_candidates": candidates,
        "revert_chain": revert_chain,
        "co_changed": co_changed,
        "co_changed_totals": co_changed_totals,
        "snippet": snippet,
        "activity": activity,
        "commands": commands,
        "limits": {"max_commits": max_commits, "since": since,
                   "truncated": total > max_commits,
                   "max_candidates": max_candidates,
                   "candidate_cap_reached": cap_state["hit"],
                   "co_changed_per_commit": max_co_changed},
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


def _at_least_one(raw):
    """An argparse type for `--max-co-changed`, mirroring scan.py's
    `_at_least_one` for `--min-lines`.

    A cap below 1 is not a request the ranking loop can honor: `ranked[:n]`
    for `n <= 0` silently keeps zero or (for a negative `n`) drops paths
    off the *end* of the ranked list instead of capping it, which is the
    opposite of a cap. Rejecting it here keeps that a usage error with a
    readable message instead of a quietly wrong result.
    """
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(
            "must be 1 or greater, got {}".format(value))
    return value


def main():
    ap = argparse.ArgumentParser(description="Trace why a line of code exists.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--lines", required=True, help="START:END, e.g. 3:5")
    ap.add_argument("--max-commits", type=int, default=5000)
    ap.add_argument("--since", default=None,
                     help="e.g. '3 years ago'; unset means no time bound")
    ap.add_argument("--max-candidates", type=int, default=200)
    ap.add_argument("--max-co-changed", type=_at_least_one, default=CO_CHANGED_PER_COMMIT,
                     help="cap on co_changed paths kept per introduction "
                          "candidate; the true per-commit count is still "
                          "recorded in co_changed_totals")
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
            max_co_changed=args.max_co_changed,
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
