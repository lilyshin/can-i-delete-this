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

A third source exists for the same reason, one level further out: on a
history short enough to read directly (SKILL.md's threshold), the agent's
own reading of `git log -p --follow` is the primary evidence, not the
tracer's candidate lists -- and a commit it identifies there is not
guaranteed to be in either list at all. blame_candidates only ever holds
what plain `git blame` pointed at; introduction_candidates only ever holds
what blame, pickaxe or line-history actually turned up (see trace.py's
`add()`). None of those three searches is guaranteed to surface every
commit a human reading the full diff-by-diff history would notice, most
concretely when a rename bundles enough unrelated change to defeat blame's
own move detection *and* the wording pickaxe would need as a needle has
since been rewritten. Refusing to honor that citation would mean the
deliverables disown an answer the agent already verified by reading the
history itself -- exactly the gap SKILL.md's restructured "When you do not
need this" section warns about. `_evidence_candidate` and
`evidence_candidates` below build a minimal stand-in candidate straight
from the verdict's own evidence item when the agent has recorded enough of
the commit's own facts (subject, date, author) to render one; `find_cited`
and `real_shas` fall back to it only after both real candidate lists come
up empty, so an evidence item that names a commit already present in one
of them (the common case) is never routed through the synthesized path.
"""

# Optional descriptive fields a `commit` evidence item may carry beyond the
# schema verdict.py enforces (`type`, `ref`, `note`), for a commit the agent
# found by reading history directly rather than through trace.py's own
# search paths. verdict.py's validate() already accepts extra keys on an
# evidence item without complaint, so no schema change was needed for this;
# these names are simply the ones citation.py, render.py and artifacts.py
# know to look for.
_EVIDENCE_DESCRIPTIVE_FIELDS = ("subject", "date", "author", "author_email")


def _evidence_candidate(item):
    """Build a minimal candidate dict from one `commit` evidence item's own
    descriptive fields, for a commit that trace.py's own search paths (blame,
    pickaxe, line-history) never surfaced.

    Returns None when the item carries none of `_EVIDENCE_DESCRIPTIVE_FIELDS`:
    a bare `{type: commit, ref: ...}` item is the ordinary case (the cited
    commit is expected to resolve against trace_data), and there is nothing
    here to render a timeline row from, so this must not manufacture one out
    of a ref alone.
    """
    if not isinstance(item, dict):
        return None
    if not any(item.get(f) for f in _EVIDENCE_DESCRIPTIVE_FIELDS):
        return None
    ref = item.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        return None
    return {
        "sha": ref.strip(),
        "subject": item.get("subject") or "",
        "date": item.get("date") or "",
        "author": item.get("author") or "",
        "author_email": item.get("author_email"),
        "why": "history-read",
    }


def evidence_candidates(evidence):
    """Every synthesized candidate `_evidence_candidate` can build from
    `evidence`'s `commit` items. See the module docstring's third source.
    """
    out = []
    for item in evidence or []:
        if not isinstance(item, dict) or item.get("type") != "commit":
            continue
        cand = _evidence_candidate(item)
        if cand is not None:
            out.append(cand)
    return out


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


def find_cited(trace_data, refs, evidence=None):
    """Find the single candidate `refs` cites, searching both lists.

    introduction_candidates is searched first, then blame_candidates, so a
    sha that happens to appear in both (a blame result that also passed
    noise filtering, which trace.py's own `add()` does add to
    introduction_candidates) resolves to the richer entry rather than the
    thinner one. `evidence` (the verdict's own `evidence` list, optional and
    None by default so every existing call site keeps its old behavior) is
    checked last, via `evidence_candidates`: a commit the agent found by
    reading history directly and described in its own citation, that never
    surfaced through blame, pickaxe or line-history at all. See the module
    docstring's third source.

    Returns (candidate, source) where source is "introduction", "blame" or
    "history-read". Returns (None, None) when `refs` is empty, or when it
    matches nothing anywhere. Callers must tell those two cases apart
    themselves: an absent citation ("nothing was cited") is not the same
    situation as a citation that does not resolve ("something was cited but
    it names no commit in this trace"). This function reports both the same
    way because the distinction lives entirely in whether `refs` was empty
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
    for e in evidence_candidates(evidence):
        if cited_as_real(e.get("sha"), refs):
            return e, "history-read"
    return None, None


def real_shas(trace_data, refs, evidence=None):
    """Every sha, across both candidate lists plus the evidence fallback,
    that `refs` cites.

    render.py uses this instead of find_cited: a verdict's evidence list
    could in principle cite more than one commit, and every row that
    matches needs the same bold "real introduction" treatment, not just
    the first one found. `evidence` is optional, None by default, for the
    same reason as in `find_cited`.
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
    for e in evidence_candidates(evidence):
        sha = e.get("sha")
        if cited_as_real(sha, refs):
            shas.add(sha)
    return shas
