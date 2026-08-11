# Changelog

## 0.2.2 - 2026-08-11

Field report from the owner running the published skill for a Korean user:
`summary`, `conditions` and the artifact prose came back in Korean as
instructed by SKILL.md rule 5, but `render.py` and `artifacts.py` hardcoded
their own English chrome around it, so the report the user actually opened
was Korean analysis wrapped in English badge labels, card headers, tag
text and artifact scaffolding.

- Added `--lang` to both `render.py` and `artifacts.py` (default `en`;
  threaded through `render()`, `write_report()`, `skeleton()` and the
  functions they call as an `en`-defaulting keyword argument), with `en`
  and `ko` supported. Every string a user reads that these two scripts
  write themselves, not data read from git or the verdict, is now looked
  up in a plain module-level `_STRINGS` dict keyed by language then by a
  dotted string key: grade badge labels, card headers, the dot legend, the
  co-changed line's label, both truncation disclosures, the candidate-cap
  note, the collapsed `<summary>` text (count still correct and escaped),
  the artifact skeletons for all four grades, the unresolved-citation
  message, the `Grade:`/`Target:` labels, and the placeholder words
  substituted when a field is missing (`unknown`, `date unknown`, and so
  on). SHAs, paths, commit subjects, author names and dates are never
  looked up in this table; they stay exactly what git or the verdict said.
  An unknown `--lang` value falls back to `en` rather than raising. No new
  dependency: no gettext, stdlib only.
- The page's `<html lang="...">` attribute now matches the language
  `render.py` actually rendered.
- Shortened the dot legend from one 748-character paragraph (761 with its
  one `<code>` tag) to four short phrases, one per state, in both
  languages (145 characters of English phrase text, 84 of Korean). The two
  nuances the long paragraph carried moved rather than disappeared: a
  filled dot that is also a noise-flagged squash already carries a second
  "also flagged noise" tag on that same row (`render.py`'s `_real_row`),
  so the legend no longer repeats it; the reasoning for why a revert chain
  survives regardless of noise scoring already lives in
  `strategy-tree.md`'s step 5, so the legend states the fact (part of a
  revert/reapply chain) without re-deriving the reason.
- `SKILL.md` rule 5 ("Respond in the user's language") now says plainly
  that this covers the report and the artifact, not only the agent's own
  prose, and the workflow's render/artifacts invocation in both
  `SKILL.md` and `strategy-tree.md` passes `--lang` to match.
- Added `tests/test_localization.py`: `--lang ko` renders Korean chrome
  around untouched data, default and explicit `en` are byte-identical, an
  unknown lang value falls back to `en` without raising, the collapsed
  `<summary>` count is correct and escaped in both languages, a combined
  injection payload stays escaped in a `ko` render, and the `lang`
  attribute matches. All 183 pre-existing tests still pass unmodified,
  proven by diffing this release's default-`en` output against the
  previous release's for the same fixtures before writing a single new
  string.

## 0.2.1 - 2026-08-07

Field-report fix: a real trace on a file with two renames was miscounted
by the size check, which then skipped the tracer and produced no report.

- Fixed the history-size threshold command in `SKILL.md`, `README.md` and
  `strategy-tree.md` from `git log --oneline -- <path> | wc -l` to
  `git log --oneline --follow -- <path> | wc -l`. Without `--follow`, the
  count only includes commits touching the file's *current* path, so a
  renamed file comes back undercounted; the field case counted 4 commits
  without `--follow` against a real count of 21 with it, and the tracer
  was skipped as a result.
- Restructured the "when you do not need this" framing into "the tracer
  always runs; the threshold decides how you read, not whether you
  report" in `SKILL.md`, `README.md` (including its Korean summary) and
  `strategy-tree.md`. The tracer now always runs regardless of history
  size, because it is what produces the report, the mechanically-checked
  evidence and the artifact; previously a short history skipped the
  tracer entirely, which meant it also skipped every deliverable. The
  threshold still decides where the agent's understanding of intent comes
  from: past it, the tracer's ranked candidates; at or under it, the
  agent's own reading of `git log -p --follow`, which remains the more
  reliable source at that size and is still worth saying so plainly.
- Fixed a citation gap this restructuring exposed: a commit the agent
  found by reading history directly, that never surfaced through blame,
  pickaxe or line-history at all (a rename bundled with unrelated change
  can defeat blame's own move detection, past what pickaxe's
  current-content needles recover), used to resolve exactly like a stale
  or mistyped citation, an "unresolved" attribution that neither the HTML
  report nor the paste-ready artifact would name. Fixed in `trace.py`, not
  `citation.py`: a new `--include-commit <sha>` option (repeatable;
  `include_commits` in `trace()`) looks the sha up against the repository
  with `gitq.commit_meta`, refuses a nonexistent or mistyped sha into
  `notes` instead of silently accepting it, and adds a verified sha to
  `introduction_candidates` with `why: "cited"` and its real subject, date
  and author read from git, bypassing noise exclusion and the candidate
  cap the same way blame's own results already do. `citation.py` still
  only ever matches `introduction_candidates` and `blame_candidates`; it
  never reads descriptive fields off a verdict's own evidence, because
  those come from the agent, not from git, and this project's facts come
  from git only. (An earlier draft of this fix did read those fields
  directly in `citation.py`, and a review caught that it rendered a
  fabricated subject on a nonexistent sha as a verified "real
  introduction" indistinguishable from one the tracer had actually
  checked; that version never shipped, but see
  `TestFabricatedCitationIsRejected` in `tests/test_citation_resolution.py`
  for the exact scenario, pinned as a permanent regression test.)
- Added `build_two_renames` to `tests/fixtures/make_fixture_repo.py`, and
  `TestTwoRenames` in `tests/test_trace_cases.py`, pinning that a file
  renamed twice still resolves to its real introducing commit through the
  tracer and that its `--follow` history count exceeds its no-follow
  count. Added `TestExplicitlyIncludedCommit` and
  `TestFabricatedCitationIsRejected` in `tests/test_citation_resolution.py`
  for the `--include-commit` fix above.

## 0.2.0 - 2026-08-06

Report and search-quality release, driven by a first run against a real
six-year-old production repository.

- `render.py` now leads with the answer: section order is verdict badge,
  summary, conditions, evidence, next-step artifact, history, notes. History
  moved last because it is supporting evidence, not the answer.
- History collapses into a native `<details>` block once it exceeds twelve
  rows. The commits the verdict cites, every `blame` candidate, and the
  revert chain stay outside the collapse; short traces are not collapsed at
  all.
- `conditions` renders as a checklist, so a `conditional` verdict reads as
  "verify these before deleting" rather than as prose.
- `trace.py` ranks pickaxe needles instead of taking the first five tokens:
  language keywords and ubiquitous tokens are dropped, identifier-shaped
  tokens are preferred, and the top candidates are rarity-checked with
  `git grep` so a token appearing across many files is deprioritized.
- Pickaxe now searches path-scoped first with up to three needles, then
  repo-wide with only the rarest one or two. Repo-wide search is kept
  because a function moved between files is only findable that way.
- `notes` records when needles were rejected as common and when repo-wide
  search used a reduced set.
- `grep` added to the read-only allowlist (sixteen subcommands) for the
  rarity check.
- `run_git` now sanitizes the execution environment and injects
  `-c core.pager=cat -c diff.external=`, and refuses `-O` as a write flag.
  `git grep -O` is git's short form of `--open-files-in-pager`, which the
  long-form prefix check did not catch; the environment sanitization closes
  the same class of hole for config-driven external programs rather than
  relying on the flag list alone. The user's own `GIT_CONFIG_GLOBAL` and
  `GIT_CONFIG_SYSTEM` are deliberately left untouched.

Measured on a 193-line file in a repository with years of history: candidate
count 200 (cap reached) to 12 (cap not reached), tracer wall time 37s to 4s,
with the real introducing commit preserved in both.

## 0.1.0 - 2026-08-06

Initial release.

- Read-only git layer (`gitq.py`): blame, pickaxe, line-history, rename-follow.
- Noise classifier (`noise.py`) covering ten debris categories (N1-N3,
  N5-N11; N4, file move/rename, is documented in the catalog but is not a
  `noise.py` classifier category, since `git blame`'s own similarity
  detection handles it): formatter/linter sweeps, import sorts, license
  headers, code moves, vendoring, generated code, upgrade sweeps, merge
  commits, squash history, typo/comment-only edits. See
  `skills/can-i-delete-this/noise-catalog.md`.
- Strategy-tree tracer (`trace.py`) that falls back from `blame` to pickaxe
  and line-history search when blame's candidate is noise or empty.
- Verdict schema and validator (`verdict.py`): four grades
  (`danger`/`conditional`/`safe`/`unknown`), every graded verdict above
  `unknown` requires a commit reference.
- Self-contained HTML report renderer (`render.py`): dark and light mode,
  no external assets, blame-vs-real-introduction timeline.
- Paste-ready next-step artifact generator (`artifacts.py`): keep-comment,
  checklist, PR body, or question, with clipboard support.
- `SKILL.md` plus reference docs (`noise-catalog.md`, `strategy-tree.md`,
  `CREATION-LOG.md`) that were shaped by measured pressure-test baselines,
  not by guessing what an agent needs.
- Plugin metadata for Claude Code (marketplace + plugin manifest) and a
  cross-runtime install path for Codex/Copilot CLI/Gemini CLI (`AGENTS.md`).
