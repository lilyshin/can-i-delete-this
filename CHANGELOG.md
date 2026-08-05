# Changelog

## 0.1.0

Initial release.

- Read-only git layer (`gitq.py`): blame, pickaxe, line-history, rename-follow.
- Noise classifier (`noise.py`) covering eleven debris categories (N1-N11):
  formatter/linter sweeps, import sorts, license headers, renames, code
  moves, vendoring, generated code, upgrade sweeps, merge commits, squash
  history, typo/comment-only edits. See `skills/can-i-delete-this/noise-catalog.md`.
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
- Plugin metadata for Claude Code (marketplace + plugin manifest) and for
  Codex/Copilot CLI/Gemini CLI (`.codex-plugin/plugin.json`, `AGENTS.md`).
