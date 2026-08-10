"""Resolve which commit, if any, the verdict's evidence cites as the real
introduction.

trace.py cannot know which candidate is real: the verdict deciding that is
written after the tracer runs (see render.py's module docstring for the
fuller argument). Both render.py and artifacts.py need to answer the exact
same question -- "which candidate does verdict['evidence'] cite as the
introducing commit, and where is it" -- so the matching logic lives here
once instead of twice.

The cited commit can live in either of trace.py's two candidate lists:

- introduction_candidates: survived noise filtering. Richer shape (why,
  author_email, files_changed).
- blame_candidates: everything plain `git blame` pointed at, noise or not.
  Thinner shape (sha, subject, date, author, noise).

A squash commit that noise.py correctly flags (N10 is the common case) is
filtered OUT of introduction_candidates entirely -- see trace.py's `add()`,
which returns early on `v.is_noise` before a commit ever reaches that list.
SKILL.md's workflow and noise-catalog.md's N10 entry both then instruct the
agent to read that noise-flagged commit's own diff and cite it anyway when
the diff is what actually added the target lines: N10 distrust is about
the commit's *message*, not its *diff*. When an agent follows that
instruction, the cited sha exists only in blame_candidates. Refusing to
look there would make render.py and artifacts.py contradict the very
workflow SKILL.md teaches.

Deliberately not a third source: a commit an agent identifies by reading
`git log -p --follow` directly (SKILL.md's short-history path), that
blame, pickaxe and line-history all failed to surface at all. This module
never accepts a description of that commit from the verdict's own
evidence -- an evidence item's `subject`/`date`/`author` are exactly what
this project must never treat as fact, since they did not come from git,
they came from whatever the agent typed. The fix for that case lives in
trace.py instead: re-run it with `--include-commit <sha>`, which looks the
sha up with `gitq.commit_meta` (so a fabricated or nonexistent sha is
rejected there, not rendered here) and, once verified, adds it to
`introduction_candidates` with `why: "cited"`. After that re-run, the cited
commit is an ordinary introduction_candidates entry with real git metadata,
and this module's existing two-list search resolves it with no further
change.
"""


def commit_refs(evidence):
    """Lowercased, non-empty commit refs cited as evidence in a verdict."""
    refs = []
    for item in evidence or []:
        if not isinstance(item, dict) or item.get("type") != "commit":
            continue
        ref = item.get("ref")
        if isinstance(ref, str) and ref.strip():
            refs.append(ref.strip().lower())
    return refs


def cited_as_real(sha, refs):
    """True when `sha` matches one of `refs`.

    Refs are usually short shas, so the match is a prefix match against the
    full sha, not equality.
    """
    sha = str(sha or "").lower()
    if not sha:
        return False
    return any(sha.startswith(ref) for ref in refs if ref)


def find_cited(trace_data, refs):
    """Find the single candidate `refs` cites, searching both lists.

    introduction_candidates is searched first, then blame_candidates, so a
    sha that happens to appear in both (a blame result that also passed
    noise filtering, which trace.py's own `add()` does add to
    introduction_candidates) resolves to the richer entry rather than the
    thinner one.

    Returns (candidate, source) where source is "introduction" or "blame".
    Returns (None, None) when `refs` is empty, or when it matches nothing
    in either list. Callers must tell those two cases apart themselves: an
    absent citation ("nothing was cited") is not the same situation as a
    citation that does not resolve ("something was cited but it names no
    commit in this trace"). This function reports both the same way
    because the distinction lives entirely in whether `refs` was empty
    going in, which the caller already knows.
    """
    if not refs:
        return None, None
    for c in trace_data.get("introduction_candidates") or []:
        if cited_as_real(c.get("sha"), refs):
            return c, "introduction"
    for b in trace_data.get("blame_candidates") or []:
        if cited_as_real(b.get("sha"), refs):
            return b, "blame"
    return None, None


def real_shas(trace_data, refs):
    """Every sha, across both candidate lists, that `refs` cites.

    render.py uses this instead of find_cited: a verdict's evidence list
    could in principle cite more than one commit, and every row that
    matches needs the same bold "real introduction" treatment, not just
    the first one found.
    """
    shas = set()
    for c in trace_data.get("introduction_candidates") or []:
        sha = c.get("sha")
        if cited_as_real(sha, refs):
            shas.add(sha)
    for b in trace_data.get("blame_candidates") or []:
        sha = b.get("sha")
        if cited_as_real(sha, refs):
            shas.add(sha)
    return shas
