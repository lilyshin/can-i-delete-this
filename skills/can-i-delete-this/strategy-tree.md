# Strategy Tree

What `scripts/trace.py` actually runs, in order, and what to do by hand when a
step comes up empty. `trace.py` runs steps 1 to 5 for you in one call; this
document exists for the moments it is not enough on its own. All commands
below go through `gitq.run_git`, which only allows read subcommands
(`blame`, `log`, `show`, `diff`, `rev-parse`, `rev-list`, `cat-file`,
`ls-files`, `ls-tree`, `merge-base`, `name-rev`, `describe`, `for-each-ref`,
`shortlog`, `var`) and refuses any global flag or write-adjacent flag.

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

## 3. Pickaxe on needles drawn from the target lines

```
git log --format=%H -S '<needle>' --max-count=<max_commits> [--since=<since>]
```

Needles are up to five distinct tokens (`[A-Za-z_][A-Za-z0-9_.]{3,}`) pulled
from the target lines' current content, tried one at a time, across full
history by default. `-S` finds the commit that changed a string's *count* of
occurrences, which crosses file renames and moves because it searches by
content, not by path.

**Comes up empty:** the needles were not distinctive enough (too generic, or
the line is mostly punctuation and keywords). Widen the line range so more
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
scored as noise, most often N10 (a squash commit shaped like a PR title). A
squash commit is untrustworthy by its *message*, not its *diff*: it is
excluded from `introduction_candidates` because its subject cannot be
trusted to describe intent, not because its content is unrelated to the
target line.

```
git show <sha> -- <path>
```

If that diff is what actually introduced the target lines, it is the real
introducing commit, and you may cite it as evidence even though `noise.py`
flagged it. This is the one place a human reading a diff outperforms the
tracer's own scoring: the tracer cannot tell "this commit's message hides a
real change" apart from "this commit's message accurately describes noise",
so it treats both the same way, conservatively. Reading the diff can tell
the difference.

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
   better than any prose.
2. **The PR body and linked issue.** A subject ending in `(#123)` is a
   pointer to a forge page git does not contain; go read it there.
3. **Adjacent comments.** `git show <sha> -- <path>` for the full diff
   context around the target lines, not just the lines themselves.
4. **CHANGELOG or release notes**, if the repository keeps one, for the date
   range around the introducing commit.

**Comes up empty (no test, no PR reference, no comment, nothing):** this is
what `unknown` is for. Do not promote your best guess to `safe` or `danger`
because the investigation was thorough; thoroughness is not evidence.

## 8. Grade and hand over

Write the verdict object (schema enforced by `scripts/verdict.py`), run it
through `validate()`, then:

```
python3 render.py --trace t.json --verdict v.json
python3 artifacts.py --trace t.json --verdict v.json --copy
```

If `limits.truncated` or `limits.candidate_cap_reached` is true anywhere in
this tree, say so in the final summary regardless of which step you were on
when you stopped; the tracer already computed both flags for you in
`trace.py`'s output, it is not extra work to pass them on.
