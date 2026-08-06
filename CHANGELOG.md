# Changelog

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
