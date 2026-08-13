# Noise Catalog

Eleven ways a commit can sit on top of `git blame`'s answer without being the
reason the code exists. `scripts/noise.py` implements the checks below;
`gitq.blame_shas` already runs `blame -w -C -C -C`, which handles some of
these before noise scoring ever runs. Fixture references point at the
regression test that proves each case.

## Signals filter. Hints do not. (0.7.0)

A commit is filtered out of `introduction_candidates` on **what it changed**:
the diff, the paths, the commit graph. It is never filtered on **how its
author described the change**.

| | Read from | Sets `is_noise` | Categories |
|---|---|---|---|
| **Signals** | diff content, file paths, parent count, per-file churn | Yes | N1, N2, N5, N6, N7, N9 |
| **Hints** | the subject line, matched against English vocabulary | Never | N3, N8, N10, N11 and the vocabulary halves of N1, N5, N7 |

Until 0.7.0 the subject did the filtering, and that failed in two directions
at once.

It failed for every language but English. A 25-file quote-style sweep titled
`잡일: 저장소 전체 포맷터 적용` scored `is_noise: false` with zero signals,
while the identical commit titled `chore: apply formatter` scored N1. The fix
is not a Korean lexicon: the next repository writes Japanese, or German, or
`cleanup`, or nothing recognizable at all. The fix is to stop reading the
subject to decide.

It also failed in the dangerous direction, in English. Measured against a
20,000-commit internal Android repository: for one target line, the commit
`blame` reported touched 310 files with a PR-shaped subject, so the old N10
rule discarded it. Its diff **on the target file** was 6 lines removed and 18
added. It wrote the line being asked about, and it was being dropped from the
candidate list on the shape of its subject. Leaving debris in the list costs
the agent one extra read; discarding the real introducing commit cannot be
recovered downstream at all.

So vocabulary now produces a `hints` entry alongside `signals` in the tracer's
JSON, and the agent (which reads subjects in any language, and reads the diff
too) weighs it. A hint is a claim the commit makes about itself, and it is
reported as such: `subject matches formatter vocabulary (English)`, or
`PR-title shaped subject over 310 files: the subject may name the pull
request rather than this change`.

**What this cost, measured on the same repository:** roughly 8% more wall
time (one extra path-scoped `git show` per scored commit, at ~15ms, cheaper
than the `commit_meta` call already being made), and 2 to 10 more candidates
per query. One query moved from 198 candidates to 200, which is the cap, so
the disclosure rule in `SKILL.md` now fires there where it did not before.
That is the trade taken deliberately.

**Cosmetic detection replaced the vocabulary it retired.** `noise.is_cosmetic`
normalizes quote characters, spacing and trailing commas or semicolons, then
compares removed and added lines pairwise in order. It catches the token-level
formatter `blame -w` cannot see through, in any language, with no commit
message at all, and it refuses two things a laxer check would accept:
reordered statements (the multiset of lines is unchanged while the code is
not) and an empty diff (no evidence must never read as evidence of debris).

## Contents

- [N1: Formatter / linter bulk apply](#n1-formatter--linter-bulk-apply)
- [N2: Import / dependency sort](#n2-import--dependency-sort)
- [N3: License / copyright header injection](#n3-license--copyright-header-injection)
- [N4: File move / rename](#n4-file-move--rename)
- [N5: In-file or cross-file code move](#n5-in-file-or-cross-file-code-move)
- [N6: Vendoring / third-party import](#n6-vendoring--third-party-import)
- [N7: Auto-generated code](#n7-auto-generated-code)
- [N8: Language / framework upgrade sweep](#n8-language--framework-upgrade-sweep)
- [N9: Merge commits](#n9-merge-commits)
- [N10: Squash / rebase history loss](#n10-squash--rebase-history-loss)
- [N11: Typo / comment-only edits](#n11-typo--comment-only-edits)

## N1: Formatter / linter bulk apply

**Signals**: `noise.py` catches this two ways. Structural: the diff is empty
once whitespace is ignored (`gitq.is_whitespace_only`), confidence 0.95,
standalone. Or the path-scoped diff is cosmetic once quotes, spacing and
trailing punctuation are normalized (`noise.is_cosmetic` over
`gitq.diff_lines`), confidence 0.9, standalone. The second check is what
covers a real formatter rewriting tokens (quote style, trailing commas),
which survives whitespace-ignoring diff; before 0.7.0 that case was caught
by English formatter vocabulary in the subject, which is now only a hint.

**Route around it**: `gitq.blame_shas` already runs `blame -w`, so pure
whitespace reformatting is defeated before noise scoring sees it. For
token-level reformatting, `trace.py` falls back to pickaxe on a needle from
the target line, which finds the commit that actually introduced that token
regardless of what a later formatter did to its quoting.

**Fixture**: F1 (`tests/test_fixture_f1.py::TestF1Fixture`,
`tests/test_trace_cases.py`). A 2023 `chore: apply formatter` commit flips
single to double quotes across 25 files, burying a 2019
`hotfix: prevent double charge (#4127)`. Unit-level scoring is covered by
`tests/test_noise.py::test_n1_whitespace_only_is_noise`,
`test_cosmetic_diff_is_noise_whatever_the_subject_says` and the
`TestCosmeticNormalization` edge cases. The same fixture rebuilt with
Korean, Japanese, German, convention-free and near-empty subjects is
`tests/test_noise_language_independence.py`.

## N2: Import / dependency sort

**Signals**: changed lines are concentrated in the import block
(`import_ratio >= 0.8`), confidence 0.95, standalone. Subject vocabulary
(`imports?|isort|goimports`) is a hint only, and filters nothing.

**Route around it**: if the target line itself is an import statement, this
is not noise to route around, it is the actual question; reframe what you are
investigating. Otherwise the structural check removes the commit from
`introduction_candidates` without any extra step.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_n2_high_import_ratio_is_noise`. `import_ratio` is
never computed by `trace.py` today (`noise.score` is always called with the
default `import_ratio=0.0`), so this path is reachable only if a caller
passes the value explicitly.

## N3: License / copyright header injection

**Hint only, no signal.** The subject mentioning
`licen[cs]e|copyright|header|spdx` is reported as a hint and filters nothing.
A header injection whose diff really is confined to the top of each file will
usually be caught by N1's cosmetic check on the target path instead (the
target line's own diff comes back empty, so the commit never becomes a
candidate for that line to begin with). "fix: correct HTTP header parsing
bug" is why this stays a hint: the word is in both.

**Route around it**: exclude the file's top N lines (wherever the header
block ends) and re-run the trace on the remaining range.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_license_vocabulary_hints_but_does_not_filter`.

## N4: File move / rename

**Signals**: the same content reappears at a different path. This is not a
`noise.py` category at all; `git blame`'s own similarity detection handles a
plain rename with zero extra flags. It only becomes a trap when the rename
commit also bundles unrelated changes (new helpers, other edits), which drops
post-rename similarity below the threshold blame needs to keep following the
file's identity.

**Route around it**: `gitq.blame_shas` already asks for `-C -C -C`
(detect copies from modified, unmodified, and other-commit files) plus `-w`.
When a bundled rename still defeats that, `trace.py`'s pickaxe fallback
recovers the real commit anyway, since `-S` searches full history by content,
not by path.

**Fixture**: F2 (`tests/test_trace_cases.py::TestF2Rename`). A rename commit
also inserts six unrelated helper functions ahead of the moved code, which
empirically breaks blame's rename-follow (three to four helpers still let it
through; six does not).

## N5: In-file or cross-file code move

**Signals**: a pure rename, structurally: git's own `old => new` notation on
every changed path in `--numstat`, with zero added and removed lines,
confidence 0.9. That covers the plain move.

It does not cover the trap this category is named for. A function moving to a
different file with the origin left behind rather than deleted is not a
rename in git's eyes, produces real line churn on both sides, and no signal
in `noise.py` catches it. What recovers the real commit there is `trace.py`'s
pickaxe fallback (see "Route around it" below), not a noise signal. The
`move|relocate|reorganiz|restructur|extract` vocabulary is a hint only, and
deliberately so: it was the most dangerous filter this project shipped.

**Route around it**: `blame -C -C -C` is documented to detect lines moved or
copied from other files modified in the same commit, but empirically it does
not always resolve this case (confirmed: it still misattributes to the move
commit when the origin file is emptied rather than deleted). The pickaxe
fallback in `trace.py` recovers the real commit through the moved code's own
content, independent of which file it lived in.

**Fixture**: F3 (`tests/test_trace_cases.py::TestF3Move`). `retry_once` moves
from `util.py` to `net.py`; the origin file is emptied to a comment, not
removed, which keeps blame from taking the plain-rename shortcut. Since 0.7.0
the filtering signal here is structural: git's own rename notation in
`--numstat` (`old => new`) on every changed path with zero line churn, which
needs no extra invocation and no vocabulary
(`tests/test_noise.py::test_pure_rename_is_noise`,
`test_rename_carrying_edits_is_not_a_pure_rename`). The `move|rename|extract`
vocabulary is a hint
(`test_move_vocabulary_hints_but_does_not_filter`), and it is the hint whose
promotion to a filter was most dangerous: an extraction is exactly where a
line is often introduced.

## N6: Vendoring / third-party import

**Signals**: every changed path matches a vendor directory
(`vendor/`, `third_party/`, `node_modules/`, `Pods/`, `external/`, `deps/`),
confidence 0.95, standalone.

**Route around it**: the structural check excludes the commit from
`introduction_candidates` outright, even when a needle from the target line
happens to also occur inside the vendored dump (a coincidental pickaxe hit).

**Fixture**: F6 (`tests/test_trace_cases.py::TestF6Vendor`). One vendored
file deliberately contains the token `load_config`, one of the target line's
pickaxe needles, so the vendor commit is a genuine pickaxe hit that N6 must
still exclude. Unit-level: `tests/test_noise.py::test_n6_vendored_paths_only`.

## N7: Auto-generated code

**Signals**: structural, every changed path matches a generated-file hint
(`_pb2.py`, `.pb.go`, `_generated.`, `.gen.`, `generated/`, `.g.dart`,
`_pb.js`), confidence 0.95. The subject mentioning
`generated|codegen|regenerate|proto|protobuf|swagger|openapi` is a hint and
filters nothing: a hand-written commit can discuss protobuf, and a generated
dump can arrive with no message at all.

**Route around it**: the generated file is not where intent lives. Move the
investigation to the generator's input (the `.proto`, the schema, the
template) instead of chasing commits to the generated output.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_n7_generated_hints_in_paths` and
`test_generated_vocabulary_hints_but_does_not_filter`.

## N8: Language / framework upgrade sweep

**Hint only, no signal.** The subject mentioning
`upgrade|bump|migrate to|port to|modernize|deprecat` is reported and filters
nothing. "fix: bump connection pool size to handle burst load" is a real fix
with the same vocabulary.

**Route around it**: move the search window to before the upgrade commit;
the syntax changed but the reason for the code likely predates it. When the
sweep really was mechanical, N1's cosmetic check on the target path is what
excludes it.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_upgrade_vocabulary_hints_but_does_not_filter`.

## N9: Merge commits

**Signals**: structural, `parents_count > 1`, confidence 0.95, and it takes
priority over every other signal (checked first, never overridden).

**Route around it**: a merge that resolves a real conflict can still be the
commit blame reports, when the hand-resolved line matches neither parent
verbatim. `trace.py`'s pickaxe path recovers the real feature commit through
a token from that side of the conflict, independent of the merge.

**Fixture**: F7 (`tests/test_trace_cases.py::TestF7Merge`). Two branches each
add a different keyword argument to the same call; the conflict resolution
combines both, so blame attributes the combined line to the merge commit
itself. Unit-level: `tests/test_noise.py::test_n9_merge_commit` and
`test_n9_priority_over_whitespace`.

## N10: Squash / rebase history loss

**Hint only, no signal, and this is the category that proved the rule.** A
subject shaped like a PR title (`... (#123)`) over 20 or more files is
reported as `PR-title shaped subject over N files: the subject may name the
pull request rather than this change`, and filters nothing.

Until 0.7.0 it filtered, and the route-around below existed to undo that
filtering by hand. The measured failure: on a 20,000-commit repository, the
commit `blame` reported for a target line touched 310 files with a PR-shaped
subject and was discarded, while its diff on that one file was 6 lines
removed and 18 added. It wrote the line. Distrust of a *description* had been
turned into deletion of *evidence*.

**Route around it**: the distrust is still correct, and it is still about the
commit's *message*, not its *diff*. Read the diff rather than the subject:

    git show <sha> -- <path>

If that diff is what actually added the target lines, it is the real
introducing commit, and you cite it as evidence (tag it `role: "introduced"` in the verdict's evidence, per
`scripts/verdict.py`'s `EVIDENCE_ROLES`; see SKILL.md's Grading section).
Only when the diff itself is genuinely unrelated to the target lines (the
noise commit really did just reformat, and the target lines came from
somewhere else entirely) is `unknown` the honest answer; do not manufacture
a citation out of the only remaining candidate just because it is the only
one left. See `strategy-tree.md` step 6 for the fuller walkthrough of this
same point.

**Fixture**: F4 (`tests/test_trace_cases.py::TestF4Squash`). A single squash
commit both rotates session tokens and reformats the module. Before 0.7.0
`introduction_candidates` came up empty here and the diff-reading route was
the only way to a citation; now the squash reaches the candidate list
directly, carrying the PR-title hint, and reading its diff confirms it added
the `if s.idle_seconds > 900: s.rotate_token()` guard. The verdict is the
same `danger` citing that commit; the agent is no longer required to
disbelieve a filter to get there
(`tests/test_citation_resolution.py::TestBlameOnlyCitation`). Unit-level:
`tests/test_noise.py::test_squash_pr_shape_hints_but_does_not_filter`.

## N11: Typo / comment-only edits

**Hint only, no signal.** The subject mentioning
`typo|typos|comment|comments|wording|spelling|docs?` is reported and filters
nothing. "fix: strip HTML comments during sanitization" is a real fix that
matches it.

**Route around it**: if the target is a code line, not a comment or string,
re-run the trace restricted to code lines; the intent predates this edit. A
genuinely comment-only edit to the target line is caught by N1's cosmetic
check only when the normalized text matches, so a reworded comment stays a
candidate and needs the one-line read.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_typo_vocabulary_hints_but_does_not_filter`.
