# Changelog

## 0.8.0 - 2026-08-13

Batch mode. Until now the skill needed a target you already suspected,
which was the observed adoption barrier: working through an AI chat, you
rarely stop to wonder whether a particular function is still needed.
`scan.py` inverts that. It finds blocks of commented-out code under a path
and attaches the commit that commented each one out, oldest first.

The signal was chosen by measurement against a 1710-file Kotlin
repository, not by taste:

| Signal | Result | Decision |
|---|---|---|
| Unreferenced files, by filename | 21 of 150 sampled, of which 2 were plausible (10% precision) | rejected |
| Unreferenced symbols | Needs a per-language adapter; a Python sample scored zero, because a module name is not a symbol | deferred |
| Commented-out blocks | 18 across 1710 files (1%), median 4 lines | shipped |

The third also plays to what this project can do that a linter cannot. A
linter can say code is unreachable. Only the history can say it was
commented out during an incident under a commit body reading "restore
after #3391", four years ago.

- New `scripts/scanner.py`, pure and git-free: a run of consecutive line
  comments is a block only when the run itself is at least 3 lines long,
  at least 3 of its non-blank lines carry syntax prose would not, and
  those code-shaped lines make up at least 70% of the non-blank total. A
  short run at a perfect ratio still misses the count gate and is not a
  block. A TODO line inside a run ends the run instead of
  being dropped from it, so a note between two commented-out fragments
  separates them rather than joining them. Blank comment lines stay in the
  block's span but leave the ratio's denominator, because a commented-out
  function has blank lines in it and counting them as prose rejected the
  block.
- New `scripts/scan.py`: enumerates with `ls-files`, reads each file at
  HEAD, and blames each block to find the commit that commented it out.
  When a block carries several blame shas, the oldest is reported with
  `touched_by_commits` naming how many there were, since "how long has
  this been sitting here" is measured from when the block started.
  Vendored, generated, unsupported and oversized files are skipped and
  counted in `limits`, and so is a tracked file `ls-files` lists but `show
  HEAD:<path>` cannot read (`files_missing_at_head`). A failed blame leaves
  the candidate in place with `commented_out_by: null`, because failing to
  learn a fact is not the same as the candidate not existing.
- `look_first` marks a candidate whose commenting commit mentions an
  incident, a revert, a rollback or a temporary disable, in English or
  Korean. It is an ordering hint. It filters nothing and grades nothing,
  which is the distinction 0.7.0 drew for subject vocabulary generally.
- New `artifacts.scan_checklist` and `artifacts.py --scan`: a markdown
  checklist to paste into an issue, carrying each block's path and line
  range, its age, and the commenting commit's sha, subject and first body
  line. Checkbox syntax is written literally, since 0.2.2 built it from an
  escape sequence Python read as octal and shipped broken checkboxes in
  every version until 0.2.3.
- New `/can-i-delete-this:scan <path>` command and `batch-mode.md`. Both
  say the same thing in different words: the scan grades nothing, and a
  list of plausible-looking "safe" judgements nobody verified is the
  failure this project exists to prevent.
- Nothing in the scan output uses a grade word. Grading a candidate means
  running the ordinary single-target workflow on it, with every
  non-negotiable rule in `SKILL.md` in force.
- The README now states that the four artifacts are how a verdict
  outlives its report (a keep-comment in the code, a pull request body in
  git history, a question addressed to an author), and that there is no
  cache on purpose: a stored verdict goes stale silently, while a comment
  travels with the line it describes.

## 0.7.0 - 2026-08-13

Noise classification no longer reads the commit subject to decide anything.
A subject is a description of a change, written in whatever language its
author speaks under whatever convention (or none) their repository follows,
and filtering on it failed in both directions at once.

It failed for every language but English: a 25-file quote-style sweep titled
`잡일: 저장소 전체 포맷터 적용` scored `is_noise: false` with zero signals,
while the identical commit titled `chore: apply formatter` scored N1. Adding
a Korean lexicon would not have fixed it, because the next repository writes
Japanese, or German, or `cleanup`.

It also deleted evidence in English. Measured against a 20,000-commit
Android repository: for one target line, the commit `git blame` reported
touched 310 files with a PR-shaped subject, so the old N10 rule discarded it
from `introduction_candidates` entirely. Its diff on the target file removed
6 lines and added 18. It wrote the line being asked about, and was dropped
on the shape of its subject.

- `noise.py` now separates **signals** from **hints**. Signals are computed
  from the diff, the file paths, the parent count and per-file churn, and
  they alone set `is_noise` and remove a candidate. Hints are vocabulary
  matches on the subject; they are reported in the tracer's JSON as
  `noise.hints` and filter nothing. N1, N2, N5, N6, N7 and N9 keep a
  filtering signal; N3, N8, N10, N11 and the vocabulary halves of N1, N5
  and N7 become hints.
- New signal, `noise.is_cosmetic` over `gitq.diff_lines`: normalize quote
  characters, spacing and trailing commas or semicolons, then compare
  removed and added lines pairwise in order. This is what replaced the
  formatter vocabulary, and it covers the token-level formatter `blame -w`
  cannot see through in any language, with no commit message at all. It
  deliberately refuses two things a laxer check would accept: reordered
  statements (identical multiset of lines, different behavior) and an empty
  diff (no evidence must never read as evidence of debris).
- New signal for a pure rename, from git's own `old => new` notation in
  `--numstat` with zero line churn. No extra invocation: `gitq.Commit`
  gained a `churn` field parsed from the `--numstat` output `commit_meta`
  already fetched and discarded.
- `gitq.diff_lines` is the first call in this project to render a diff body.
  It is scoped to the path under investigation, which is both cheaper and
  more precise (a repo-wide sweep that also changed real logic elsewhere is
  not debris for *this* file), passes `--no-ext-diff` explicitly on top of
  the `-c diff.external=` every invocation already carries, and returns
  empty for a diff over 400KB, which callers must treat as unknown.
- `SKILL.md` gains rule 7: read every candidate's subject yourself, in
  whatever language it is written, and treat `hints` as claims rather than
  findings. The model in this pipeline reads every language; a regex reads
  one.
- Measured cost of the trade, same repository: about 8% more wall time
  (20.4s to 22.0s, 28.4s to 32.8s on the queries benchmarked) and 2 to 10
  more candidates per query. One query moved from 198 candidates to 200,
  which is the cap, so the disclosure rule now fires there where it did
  not before. Leaving debris costs the agent one extra read; discarding the
  real introducing commit cannot be recovered downstream.
- F4's squash commit now reaches the candidate list carrying the PR-title
  hint, instead of being filtered and needing an agent to disbelieve the
  filter to find it. That closes the blind spot `CREATION-LOG.md` recorded
  from a pressure re-run, where two runs against this fixture reached
  different answers by defensible routes and the one that ignored the
  filter was the more useful.
- Every candidate now carries its commit `body` alongside the subject, in
  both `introduction_candidates` and `blame_candidates`. The subject is
  where filtering stopped looking; the body is where intent usually lives,
  and `fix: guard charge` grades nothing while its body naming the incident
  grades `danger`. `gitq.commit_meta` already read it, so this costs no git
  call. Capped at 600 characters with `body_truncated` set when cut, because
  bodies are unbounded upstream (measured on the same repository: median 280
  characters, maximum 3,725) and a capped trace holds 200 candidates. An
  agent that believed it had read a whole message would stop looking, so the
  cut is disclosed rather than silent.
- Tests: `tests/test_noise_language_independence.py` builds the same
  repository six ways (English, Korean, Japanese, German, no convention,
  near-empty subject) and pins one verdict across all of them, end to end
  through `trace()`. `tests/test_noise.py` gains `TestCosmeticNormalization`
  for the normalizer's edges and rewrites every keyword-category test as a
  hint test. `tests/test_candidate_body.py` pins the body field and its
  truncation disclosure. 312 tests pass, 15 of them red before this change.

## 0.6.1 - 2026-08-13

Correctness fix, found while capturing the README's own hero screenshot.
0.5.0 added an optional `role` field to evidence items, but citation.py's
matching -- which decides render.py's bold "real introduction" tag and
artifacts.py's "// KEEP:" attribution -- never learned about it. Every
cited commit was marked the real introduction regardless of role,
including a `role: "reference"` citation naming the formatter commit that
`git blame` reports: the very thing this project exists to tell you is
not the answer, rendered as if it were.

- `citation.py` gains `real_introduction_refs`, alongside the existing
  `commit_refs`: a commit counts as the real introduction only when its
  evidence item has `role: "introduced"` or no role at all (a verdict
  written before roles existed keeps rendering exactly as it always did).
  Every other role -- `superseded`, `reference`, `guard`, `risk` -- is
  still real, cited evidence (still in the Evidence list, and in the
  arc/isolation/risk blocks when its role calls for that), but never the
  bold real-introduction tag.
- `render.py`'s two call sites (the timeline's real-row tagging and the
  reproduction commands section) now resolve "real" through
  `real_introduction_refs` instead of the unfiltered `commit_refs`.
- `artifacts.py`'s `_top()` had the same bug: it could name a
  `reference`-tagged commit in the "// KEEP:" line. It now resolves
  through `real_introduction_refs` too, and gains a "not_introduction"
  status for the case where a verdict cites commits but none of them is
  tagged as the real introduction -- falling back to
  `introduction_candidates[0]` there would be the same M2 misattribution
  the existing "unresolved" status already guards against, so the
  artifact now says plainly that nothing resolves, instead of guessing.
- New tests in `tests/test_citation_roles.py`: the exact reproduction
  (`introduced` + `reference`, only one real row), `superseded`/`risk`
  roles likewise excluded, a roleless item still marked real, the
  artifact naming the `introduced` commit even when a `reference` item is
  listed first, and a verdict citing only non-`introduced` roles
  degrading honestly rather than silently picking a candidate.

## 0.6.0 - 2026-08-12

Until now the skill had exactly one entry point: phrasing a natural-language
trigger. The owner runs this daily and had to type a full sentence every
time an argument would have done. Added a slash command, `/can-i-delete-this:check`,
so a known target skips straight past that.

- New `commands/check.md`, declared in `plugin.json`'s new `commands` key
  alongside the existing `skills` key. Accepts `path:line`, `path:start-end`,
  a bare symbol, or nothing:
  - `path:line`/`path:start-end` is already a resolved target; the command
    hands it straight to the skill.
  - A bare symbol triggers a `grep -n` lookup, and the resolved file/line is
    stated back to the user for confirmation before anything runs. This
    guards against the exact failure this project has already measured
    once: an agent answering confidently about the wrong line and
    recommending deleting it.
  - No argument at all makes the command ask what to check instead of
    guessing.
  - `allowed-tools` is `Bash, Read, Grep, Glob, Skill`: enough to resolve a
    target and hand off, nothing that can write to the user's files, so the
    command does not widen the skill's read-only design.
- The command does not restate the skill's workflow; it resolves the
  target, then invokes the `can-i-delete-this` skill for the confirmed
  `path:start-end`, so there is exactly one place the investigation steps
  are written (`SKILL.md`). `SKILL.md`'s step 1 now notes that a target
  arriving from the command is already resolved and confirmed, so an agent
  reading it does not redo the lookup.
- README's usage section and Korean summary now show the command alongside
  the natural-language form.
- New tests in `tests/test_metadata.py`: `plugin.json` declares the command,
  the command file parses and carries `description`/`allowed-tools`, that
  `allowed-tools` excludes `Edit`/`Write`, and the body references
  `$ARGUMENTS` and the skill name.

## 0.5.0 - 2026-08-12

Field report from the owner running the published skill on a real method:
the reasoning behind a `safe` verdict was sound but arrived as one dense
paragraph mixing four different kinds of fact at equal weight, and the
owner said plainly that it did not read. Decomposed, the paragraph was: the
lifetime of the reason the code existed (introduced for one purpose,
superseded when a later refactor retired that purpose), the code's current
isolation (zero callers, zero tests, one comment mention), a residual risk
(unmerged branches still call the method), and plain commit references.

- Evidence items may now carry an optional `role`
  (`scripts/verdict.py`'s `EVIDENCE_ROLES`): `introduced`, `superseded`,
  `guard`, `reference`, `risk`. `role` is additive; `validate()` already
  tolerated unlisted keys, so an evidence item that never sets it behaves
  exactly as before, but a typo in one that does now fails validation
  loudly instead of silently rendering nothing. Also added `branch` to
  `EVIDENCE_TYPES`: an unmerged branch that still calls the code under
  investigation is legitimate evidence and previously had no way to be
  expressed except as prose.
- `render.py` draws three new blocks from role-tagged evidence, all near
  the verdict rather than displacing it as the first thing in the body:
  a compact lifetime arc when evidence carries `introduced` and/or
  `superseded` (the argument for `safe`, so it renders high on the page,
  and not at all when neither role is present); isolation figures, two
  small numbers rather than a sentence, when evidence carries `guard`
  and/or `reference` (a zero count renders as 0, since "no test guards
  this" is exactly the fact that matters, but the whole block is omitted
  when no role-tagged evidence exists at all, so an unchecked isolation
  never renders as a confident zero); and a risk block for `risk`-role
  evidence, using the same `--warn-fg`/`--warn-bg` pair the truncation and
  candidate-cap disclosures already use rather than a new colour, so a
  `safe` verdict with a residual risk cannot be mistaken for risk-free.
  Every new string is localized through `_STRINGS` (`en`/`ko`); every
  data-sourced string (refs, notes) goes through the existing `_e` escape
  helper.
- Sharpened `SKILL.md`'s grading table: a residual risk outside the
  current branch does not by itself make a verdict `conditional`.
  `conditional` means "deleting is wrong unless X holds," a precondition
  to verify before deleting; an unmerged branch that will fail to compile
  if merged forward later is a consequence to disclose, not a
  precondition to check now, and stays recorded as a `risk`-role evidence
  item instead. This was ambiguous before under the table's own wording,
  and the field verdict that prompted this release was graded `safe` while
  carrying exactly this kind of residual risk. `noise-catalog.md` (N10)
  and `strategy-tree.md` (steps 7-8) now mention the roles where they
  already discuss what evidence to gather, so the manual reading path
  reaches for them too.
- New tests: role validation (a known role validates, an unknown one
  raises, `branch` validates) in `tests/test_verdict.py`; the lifetime
  arc, isolation figures, risk block, their Korean localization, and
  escaping through a role-tagged note in the new
  `tests/test_render_roles.py`. All new tests build plain dicts rather
  than a real repository, so this release adds no measurable time to the
  suite.

## 0.4.0 - 2026-08-12

Field report from the owner running the published skill on real code: the
redesigned report looked good but was thin on information a developer
actually acts on. Asked to pick additions, the owner chose three, and
explicitly did not pick a references/callers list, because a grep-based
call-site list is language-specific and would be wrong often enough to
mislead a delete decision.

- Added the target code snippet directly under the verdict block: the
  lines being judged, plus a few lines of context on each side, line
  numbers on the left, the target lines marked with a left rule in the
  grade hue. `trace.py`'s new `_compute_snippet` reads it via
  `gitq.run_git(["show", "HEAD:<path>"])` (the same shape `_tokens_from_
  target` already used for needle selection) and degrades to a short,
  localized explanation instead of an empty box or a crash when the path
  no longer exists at HEAD, the line range is past the end of the file,
  or the file is binary.
- Added recent-change-activity facts inside the History card: when the
  target lines (or, failing that, the file) were last touched, how many
  commits touched the file in the last year, and its main authors by
  commit count. Computed in `trace.py`'s new `_compute_activity`, reusing
  the line-history search the tracer already runs wherever possible so
  "last touched" reflects the target lines, not just the file, at no
  extra git call. `gitq.py` gained `file_commit_count` and
  `author_counts`, both using `--follow`, since a plain no-follow count
  undercounts a file that was ever renamed (the same bug SKILL.md already
  warns readers about for their own commands).
- Added a collapsed reproduction-commands `<details>` at the very bottom
  of the report: the actual blame, pickaxe and line-history invocations
  this trace ran, plus `git show` for the commit the verdict cites, with
  the real repo path filled in and a copy button reusing the existing
  clipboard mechanism. `trace.py` now records the literal argv of every
  search it runs in a new `commands` list (via `gitq.blame_args`/
  `pickaxe_args`/`line_history_args`, extracted from the functions that
  already built those argv lists, so the reproduction commands can never
  drift from what actually ran); a search that did not run (no needle was
  selected, line history failed) has no entry and so is never fabricated
  in the report.
- All three additions are new, additive JSON keys (`snippet`, `activity`,
  `commands`, `repo`) on `trace.py`'s output. `render.py` treats every one
  of them as optional: a trace.json from before this release, with none of
  these keys, renders exactly as it did in 0.3.0, with no new section
  appearing. Every new string is localized through the existing `_STRINGS`
  table (`en`/`ko`); source file content is escaped through the same `_e`
  helper as every other piece of data on the page.
- Deliberately not added: a references/callers list. The owner's own
  reasoning stands as the record for why.

## 0.3.0 - 2026-08-12

Visual overhaul of `render.py`'s report. The page worked but read as
generated: prose and data shared one monospace face, the palette was a
stock purple-and-grey UI kit, the verdict (the page's entire purpose) was
a small pill below a bigger heading, the timeline was a flat list with no
line connecting the commits, and the font stack carried no Korean face
even though the report now localizes to Korean.

- Split type into two roles. Prose (summary, conditions, evidence notes,
  notes, legend, card headers) now renders in a system sans stack that
  includes Korean (`-apple-system, BlinkMacSystemFont, "Pretendard
  Variable", Pretendard, "Apple SD Gothic Neo", system-ui, "Segoe UI",
  "Malgun Gothic", sans-serif`). Data (SHAs, dates, paths, the artifact
  block, commit subjects) stays on the existing monospace stack. No
  webfont, no `@font-face`, no CDN; system stacks only.
- Korean prose no longer breaks mid-word: `body` sets `word-break:
  keep-all` as the prose default, and the data-bearing selectors
  (`.date`, `.subject`, `code`, `pre`, `h1 .path`) override back to
  `word-break: break-word` so long paths and shas still wrap instead of
  overflowing.
- Replaced the palette wholesale with cooler neutrals, and dropped the
  separate purple accent entirely: each grade now owns the page's one
  saturated hue (foreground + wash), threaded from Python into four CSS
  custom properties on `<body>` (`--grade-fg-light/dark`,
  `--grade-wash-light/dark`); `:root` derives the active `--grade-fg`/
  `--grade-wash` from those once, in a dark-mode media query, so every
  rule that used to branch on grade (the real row, its tag, the checklist
  marker, button focus/hover) now reads the two derived variables instead.
  `unknown` has no hue of its own; it points at the existing neutral
  `--muted`/`--card` variables. The four values live on `<body>`, not
  `<html>`, because the test suite pins the exact byte contents of the
  `<html lang="...">` tag.
- The badge and summary are now one verdict block at the top: the grade
  label at display size in the grade hue, the summary directly under it
  at reading size in the prose face, both sitting on the grade's wash
  background. The target path and line range recede to a small
  monospace line above it.
- The timeline gained a vertical line through the dots, drawn with a CSS
  `::before` pseudo-element on the timeline container (`:has(.row +
  .row)` so a single-row timeline draws no line at all); the real
  introduction's dot renders larger and filled in the grade hue.
- Evidence, History and Notes dropped their card borders in favour of a
  plain top rule, while Conditions and the next-step artifact (what the
  reader acts on) keep the bordered card treatment, with the artifact
  card also picking up a left accent rule in the grade hue.
- No DOM structure, class name, or string this project's tests assert on
  changed: same row classes (`row real`/`row noise`/`row revert`), same
  `<details>` collapse, same escaping, same section order, same `lang`
  attribute. All 204 existing tests pass unmodified.

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
