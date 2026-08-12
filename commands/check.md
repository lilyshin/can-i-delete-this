---
description: Resolve a deletion-risk target (path:line, path:start-end, or a bare symbol) and hand off to the can-i-delete-this skill. With no argument, asks what to check instead of guessing.
allowed-tools: Bash, Read, Grep, Glob, Skill
---

# Check

Resolve the target from `$ARGUMENTS`, then hand off. This command does not
reimplement the investigation; `skills/can-i-delete-this/SKILL.md` is the
only place that workflow is written, so it stays that way.

## 1. Resolve the target

`$ARGUMENTS`: $ARGUMENTS

- **`path:line` or `path:start-end`** (the argument ends in a colon followed
  by digits, optionally `-` and more digits, e.g. `src/foo.py:42` or
  `src/foo.py:10-25`) — this is already the resolved target. No lookup
  needed; go straight to step 2.
- **A bare symbol or identifier** (no trailing `path:line`) — locate it with
  `grep -n` (use `Grep`/`Glob` first if the file isn't obvious from the
  name). If more than one match comes up, stop and list them; ask which one
  is meant instead of guessing. Once you have exactly one file and
  line/range, state it back before continuing: "Looking at `path:line` —
  is that the target?" A wrong target here is the specific failure this
  command exists to prevent: an agent once answered confidently about a
  different line than the one it was asked about, and recommended deleting
  it.
- **No argument** — do not guess. Ask the user which file/line/symbol to
  check, and stop there.

## 2. Hand off

With the target confirmed, invoke the `can-i-delete-this` skill for it (for
example, via the `Skill` tool with `skill: "can-i-delete-this"` and the
resolved `path:start-end` as `args`) and follow its workflow from there
exactly as written. Do not restate, summarize, or re-derive its steps in
this command.
