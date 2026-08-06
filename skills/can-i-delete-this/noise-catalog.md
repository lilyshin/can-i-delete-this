# Noise Catalog

Eleven ways a commit can sit on top of `git blame`'s answer without being the
reason the code exists. `scripts/noise.py` implements the structural and
keyword checks below; `gitq.blame_shas` already runs `blame -w -C -C -C`, which
handles some of these before noise scoring ever runs. Fixture references point
at the regression test that proves each case.

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
standalone. Keyword: `files_changed >= 20` and the subject matches
`fmt|format|formatter|prettier|lint|black|gofmt|...`, confidence 0.65. A real
formatter often rewrites tokens too (quote style, trailing commas), which
survives whitespace-ignoring diff, so the keyword path exists precisely for
that case.

**Route around it**: `gitq.blame_shas` already runs `blame -w`, so pure
whitespace reformatting is defeated before noise scoring sees it. For
token-level reformatting, `trace.py` falls back to pickaxe on a needle from
the target line, which finds the commit that actually introduced that token
regardless of what a later formatter did to its quoting.

**Fixture**: F1 (`tests/test_fixture_f1.py::TestF1Fixture`,
`tests/test_trace_cases.py`). A 2023 `chore: apply formatter` commit flips
single to double quotes across 25 files, burying a 2019
`hotfix: prevent double charge (#4127)`. Unit-level scoring is covered by
`tests/test_noise.py::test_n1_whitespace_only_is_noise` and
`test_n1_formatter_keyword_with_breadth`.

## N2: Import / dependency sort

**Signals**: changed lines are concentrated in the import block
(`import_ratio >= 0.8`), confidence 0.95, standalone. Keyword fallback:
`files_changed >= 20` and the subject mentions `imports?|isort|goimports`,
confidence 0.65.

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

**Signals**: keyword only. `files_changed >= 20` and the subject mentions
`licen[cs]e|copyright|header|spdx`, confidence 0.65.

**Route around it**: exclude the file's top N lines (wherever the header
block ends) and re-run the trace on the remaining range.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_n3_license_header_with_breadth`.

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

**Signals**: keyword only. `files_changed >= 20` and the subject mentions
`move|moved|relocate|reorganiz|restructur|extract`, confidence 0.65.
`noise.py` does not implement an added/removed line-balance structural
check for this category; a function moving to a different file, with the
origin file left behind rather than deleted, is a structural trap that the
keyword check alone does not catch, and nothing in `noise.py` catches it
either. What actually recovers the real commit here is `trace.py`'s
pickaxe fallback (see "Route around it" below), not a noise signal.

**Route around it**: `blame -C -C -C` is documented to detect lines moved or
copied from other files modified in the same commit, but empirically it does
not always resolve this case (confirmed: it still misattributes to the move
commit when the origin file is emptied rather than deleted). The pickaxe
fallback in `trace.py` recovers the real commit through the moved code's own
content, independent of which file it lived in.

**Fixture**: F3 (`tests/test_trace_cases.py::TestF3Move`). `retry_once` moves
from `util.py` to `net.py`; the origin file is emptied to a comment, not
removed, which keeps blame from taking the plain-rename shortcut. Keyword-only
scoring is covered by `tests/test_noise.py::test_n5_move_rename_with_breadth`.

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
`_pb.js`), confidence 0.95. Keyword fallback: `files_changed >= 20` and the
subject mentions `generated|codegen|regenerate|proto|protobuf|swagger|
openapi`, confidence 0.65.

**Route around it**: the generated file is not where intent lives. Move the
investigation to the generator's input (the `.proto`, the schema, the
template) instead of chasing commits to the generated output.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_n7_generated_code_with_breadth` and
`test_n7_generated_hints_in_paths`.

## N8: Language / framework upgrade sweep

**Signals**: keyword only. `files_changed >= 20` and the subject mentions
`upgrade|bump|migrate to|port to|modernize|deprecat`, confidence 0.65.

**Route around it**: move the search window to before the upgrade commit;
the syntax changed but the reason for the code likely predates it.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_n8_upgrade_with_breadth`.

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

**Signals**: keyword only. `files_changed >= 20` and the subject is shaped
like a PR title ending in `(#123)`, confidence 0.65.

**Route around it**: N10 distrust is about the commit's *message*, not its
*diff*. A squash commit's PR-title-shaped subject cannot be trusted to
describe intent, but that is a reason to stop reading the subject, not a
reason to stop looking at the commit at all. Before settling for `unknown`,
read the noise-flagged commit's own diff:

    git show <sha> -- <path>

If that diff is what actually added the target lines, it is the real
introducing commit, and you may cite it as evidence even though `noise.py`
flagged it N10. Only when the diff itself is genuinely unrelated to the
target lines (the noise commit really did just reformat, and the target
lines came from somewhere else entirely) is `unknown` the honest answer; do
not manufacture a citation out of the only remaining candidate just because
it is the only one left. See `strategy-tree.md` step 6 for the fuller
walkthrough of this same point.

**Fixture**: F4 (`tests/test_trace_cases.py::TestF4Squash`). A single squash
commit both rotates session tokens and reformats the module; `notes` records
that blame returned only noise and pickaxe/line-history fall back to the same
single commit, so `introduction_candidates` comes up genuinely empty. That
does not make `unknown` the right answer here: `git show 16a76ec --
session.py` shows this exact commit adding the two target lines directly (the
`if s.idle_seconds > 900: s.rotate_token()` guard), so the diff-reading route
above recovers a `danger` verdict citing `16a76ec`, not `unknown`. Unit-level:
`tests/test_noise.py::test_n10_squash_pr_with_breadth`.

## N11: Typo / comment-only edits

**Signals**: keyword only. `files_changed >= 20` and the subject mentions
`typo|typos|comment|comments|wording|spelling|docs?`, confidence 0.65.

**Route around it**: if the target is a code line, not a comment or string,
re-run the trace restricted to code lines; the intent predates this edit.

**Fixture**: no dedicated fixture repo. Covered at the unit level by
`tests/test_noise.py::test_n11_typo_docs_with_breadth`.
