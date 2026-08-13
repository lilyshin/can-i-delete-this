# Strategy Tree

What `scripts/trace.py` actually runs, in order, and what to do by hand when a
step comes up empty. `trace.py` runs steps 1 to 5 for you in one call; this
document exists for the moments it is not enough on its own. All commands
below go through `gitq.run_git`, which only allows read subcommands
(`blame`, `log`, `show`, `diff`, `rev-parse`, `rev-list`, `cat-file`,
`ls-files`, `ls-tree`, `merge-base`, `name-rev`, `describe`, `for-each-ref`,
`shortlog`, `var`, `grep`) and refuses any global flag or write-adjacent flag.

This tree runs unconditionally, on every request, regardless of history
size: SKILL.md's `git log --oneline --follow -- <path> | wc -l` threshold
decides where your understanding of intent comes from (the tracer's ranked
candidates, or your own reading of `git log -p --follow -- <path>` on a
short history), never whether this tree runs or whether a report and
artifact get produced. Do not confuse that threshold command with the
plain `git log --oneline -- <path>` (no `--follow`) used nowhere in this
document: without `--follow` it only counts commits touching the file's
*current* path, undercounting exactly the renamed-file histories this
document's steps 1, 3 and 4 exist to see past.

## 1. Blame, with move and copy detection

```
git blame -w -C -C -C --porcelain -L <start>,<end> -- <path>
```

`-w` ignores whitespace-only history, so a pure reformat is already defeated
here. `-C -C -C` follows content moved or copied across files. Each returned
sha is scored by `noise.py`; anything not flagged noise becomes an
`introduction_candidate` with `why: "blame"`.

**Comes up empty (every blame sha is noise, or blame returns nothing):**
`trace.py` records `"blame returned only noise commits; falling back to
pickaxe"` in `notes` and moves to step 3 automatically. By hand: do not trust
the blame commit's subject as the answer; go straight to pickaxe.

## 2. Score candidates against the noise catalog

Each blame sha is scored via `noise.score`, using `gitq.is_whitespace_only`
and `gitq.changed_paths`. See `noise-catalog.md` for what each `N` category
means and which fixture proves it. This step never calls git itself beyond
what step 1 and step 4 already gathered; it is pure classification.

**Comes up empty (nothing scores as noise, nothing scores as real either):**
this cannot happen for a candidate that exists; every candidate is either
noise or not. If you are unsure why a candidate scored as noise, check
`signals` in its `noise` object; it lists every signal that fired, not just
the one that set the category.

## 3. Pickaxe: path-scoped first, then repo-wide and narrower

```
git log --format=%H -S '<needle>' --max-count=<max_commits> [--since=<since>] [-- <path>]
```

Needles are ranked, not just the first tokens found. `trace.py` pulls
distinct tokens (`[A-Za-z_][A-Za-z0-9_.]{3,}`) from the target lines'
current content, drops stopwords (language keywords and ubiquitous
programming terms, e.g. `def return import self this class true false`,
since a match on one of these says nothing about which commit is
distinctive), then ranks what is left by two things: longer tokens first,
and tokens containing `_` or `.` first (they look like identifiers, not
prose words). The top few ranked tokens are then rarity-checked with
`git grep -l -F` against the current working tree; a token found in more
than about 15 files is common enough in the tree today that matching it
tells you little, so it is deprioritized (moved after the un-checked tail,
not dropped, so it is still available if nothing better exists). If every
token on the target lines turns out to be a stopword, needle selection
falls back to the old behavior, first tokens found, unranked, rather than
running pickaxe with nothing at all.

The search itself runs in two passes, in this order:

1. **Path-scoped**, `-- <path>` appended, on up to three ranked needles.
   Cheap, and it finds anything that shares the target lines' current path
   with its introducing commit.
2. **Repo-wide**, no path restriction, on only the rarest one or two of
   those needles. This is what crosses file renames and cross-file moves,
   since `-S` searches by content, not by path, so it finds the introducing
   commit even under a different filename or a different file entirely.
   It is also the expensive, junk-prone half of the search: a needle that
   turns out to be common anywhere in history, not just in the current
   tree, can still surface many unrelated commits, which is why it runs on
   fewer, rarer needles than the path-scoped pass, not skipped or gated
   behind the path-scoped pass finding nothing. A commit found path-scoped
   is not evidence that nothing needed a repo-wide search too: the
   path-scoped pass only ever sees commits that touch the *current* path,
   so a commit that introduced the target content under a different path
   (before a rename, or in a different file entirely) is invisible to it
   no matter how many needles it runs.

**Comes up empty:** the needles were not distinctive enough (too generic, or
the line is mostly stopwords and punctuation). Widen the line range so more
tokens are available, or pick a rarer token from the same block by hand and
run `gitq.pickaxe` yourself with that string. If the file was renamed, check
whether the old path has its own distinctive tokens worth trying too.

## 4. Line-history on the exact range

```
git log --format=%H -L <start>,<end>:<path> [--max-count=<max_commits>] [--since=<since>]
```

This walks the line range's own lineage, independent of pickaxe's token
search. `trace.py` treats a `RuntimeError` here (for example, an invalid
range against the file's history) as non-fatal and records
`"line history unavailable: <reason>"` in `notes` rather than failing the
whole trace.

**Comes up empty:** if `notes` shows line-history was unavailable, the line
numbers you gave may not resolve at some point in history (the file was
smaller, or did not exist yet). Recompute the range against the commit where
you believe the code was introduced, rather than against `HEAD`.

## 5. Revert / reintroduce chain

Every sha touched by any of steps 1, 3, or 4, regardless of its noise verdict
or whether the candidate cap dropped it, is checked for a subject starting
with `revert` or containing `reapply` or `reintroduce`. This is deliberate:
a revert is the strongest do-not-delete signal there is, so it must survive
even if it would otherwise be filtered as noise or capped out.

**Comes up empty:** an empty `revert_chain` is not a dead end, it just means
nothing was ever reverted and reinstated. Do not read anything into its
absence; move on to intent recovery.

## 6. When candidates are empty because everything was filtered as noise

`introduction_candidates` empty does not automatically mean `unknown`. Check
whether every entry in `blame_candidates` was filtered out only because it
scored as noise: a merge commit (N9), a cosmetic rewrite of the whole commit
(N1), a vendored or generated dump (N6, N7). Since 0.7.0 a subject alone
never causes this, so a filtered commit is one whose *change* looked like
debris commit-wide, which is a different fact from "its diff is unrelated to
the target line". A merge that resolved a conflict by hand, or a sweep that
also fixed one real thing in this file, both land here.

```
git show <sha> -- <path>
```

If that diff is what actually introduced the target lines, it is the real
introducing commit, and you may cite it as evidence even though `noise.py`
flagged it. This is the one place reading a diff outperforms the tracer's own
scoring: the tracer judges the commit as a whole, and cannot tell "wide
mechanical change that also carried one real edit here" apart from "wide
mechanical change", so it treats both the same way, conservatively. Reading
the diff for this path can tell the difference.

**Comes up empty (the noise commit's diff really is unrelated to the target
lines):** this is a genuine `unknown`. Do not manufacture a commit reference
out of the file's only remaining candidate just because it is the only one
left; a wrong citation is worse than an honest `unknown`.

## 7. Recover intent

Commit subjects are usually useless (`fix bug`, PR-title squashes). In order
of reliability:

1. **Tests added in the same commit.** Check `co_changed` for anything
   `artifacts.py`'s test-path convention would recognize (a `tests/`
   directory, a `test_`/`_test`/`_spec` filename, or a `.test.`/`.spec.`
   segment). A test added alongside the fix tells you what it guards against
   better than any prose. If you find one, it is `role: "guard"` evidence
   (`scripts/verdict.py`'s `EVIDENCE_ROLES`); if you deliberately looked and
   found none, that absence is worth recording too, since a `guard` count
   of zero next to at least one other role-tagged item is exactly what
   `render.py`'s isolation figures are for.
2. **The PR body and linked issue.** A subject ending in `(#123)` is a
   pointer to a forge page git does not contain; go read it there.
3. **Adjacent comments.** `git show <sha> -- <path>` for the full diff
   context around the target lines, not just the lines themselves. A
   comment or doc that still mentions the code without calling it is
   `role: "reference"` evidence.
4. **CHANGELOG or release notes**, if the repository keeps one, for the date
   range around the introducing commit.

While you are recovering intent, also watch for the two things that make
the strongest case for `safe`: the commit that introduced the code
(`role: "introduced"`) and, separately, a later commit that retired the
reason it existed by replacing the mechanism, removing the call site, or
migrating the behaviour elsewhere (`role: "superseded"`). Together they are
the argument `render.py` draws as a lifetime arc near the verdict. And if
you find a residual hazard that survives whatever grade you land on, most
often an unmerged branch that still calls the code and would fail to
compile if merged forward, record it as `role: "risk"` evidence (type
`branch` fits this case) rather than folding it into `conditions`; see
SKILL.md's Grading section for why that distinction matters.

**Comes up empty (no test, no PR reference, no comment, nothing):** this is
what `unknown` is for. Do not promote your best guess to `safe` or `danger`
because the investigation was thorough; thoroughness is not evidence.

## 8. Grade and hand over

If the commit you are citing is the one you found by reading history
directly (a short history under SKILL.md's threshold) rather than one
this tree's own steps surfaced, do not write it into the verdict yet.
Re-run `trace.py` once more with `--include-commit <sha>` (repeatable)
first. That looks the sha up against the repository with
`gitq.commit_meta`; a sha that does not exist is refused there (recorded in
`notes`, not silently dropped) rather than trusted on your say-so, and a
real sha gets added to `introduction_candidates` with `why: "cited"` and
its actual subject/date/author read from git, not from anything you typed.
`citation.py` itself only ever matches `introduction_candidates` and
`blame_candidates`; it does not, and must not, read descriptive fields off
an evidence item, since those came from the agent, not from git. Only once
the re-run confirms the commit does the citation belong in the verdict.

Write the verdict object (schema enforced by `scripts/verdict.py`), run it
through `validate()`, then render and hand over, passing `--lang` to match
the language you are answering in (default `en`; SKILL.md's rule 5 covers
why this matters: the report and artifact are deliverables, not just your
own prose):

```
python3 render.py --trace t.json --verdict v.json --lang ko
python3 artifacts.py --trace t.json --verdict v.json --copy --lang ko
```

If `limits.truncated` or `limits.candidate_cap_reached` is true anywhere in
this tree, say so in the final summary regardless of which step you were on
when you stopped; the tracer already computed both flags for you in
`trace.py`'s output, it is not extra work to pass them on.
