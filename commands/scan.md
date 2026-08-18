---
description: Scan a directory for commented-out code blocks and list each one with the commit that commented it out. Grades nothing; hands off to can-i-delete-this for any candidate you pick.
allowed-tools: Bash, Read, Grep, Glob, Skill
---

# Scan

`$ARGUMENTS` is the path to scan, relative to the repository root. With no
argument, scan the current directory and say so.

## 1. Run the scan

With an argument:

    python3 <skill>/scripts/scan.py --repo <repo> --path $ARGUMENTS

With no argument, omit `--path` rather than passing it with nothing after
it, which `scan.py`'s argument parser rejects; the default is already the
current directory:

    python3 <skill>/scripts/scan.py --repo <repo>

Either way, say which directory you scanned. If the session spans more than
one git repository, name the one you scanned in your answer. Do not assume
the current working directory's repository just because it is current.

## 2. Hand the list over

    python3 <skill>/scripts/artifacts.py --scan scan.json --lang <lang>

Show the checklist. Pass `--lang ko` for a Korean user, and so on.

Then say four things, in the user's language:

1. How many candidates, and the scan scope from `limits` (files scanned,
   files skipped and why). If `candidate_cap_reached` is true, say the list
   is partial, report `files_not_reached` as the number of files that were
   never opened, and offer to rerun with a higher `--max-candidates`.
2. Which candidates are marked `look_first` and why: the commit blame
   attributes to those lines mentions an incident, a revert or a temporary
   disable. That is a reading of the subject and body, not a finding about
   the code, and the same commit may turn out to be a formatter.
3. That nothing here is graded, and that grading one means
   `/can-i-delete-this:check <path>:<start>-<end>`.
4. When helping the user choose which candidate to look at, point them at
   each item's excerpt, not only its commit line. Several candidates can
   share one blame commit: a real scan returned 43 candidates of which 40
   traced to the same commit, so the commit line could not tell those 40
   apart and the block's own text was the only thing that could.

## 3. Do not grade the list yourself

Do not write verdicts for the candidates in this command, and do not call a
block safe to delete. The scan gathered facts; a grade needs the single
target workflow in `skills/can-i-delete-this/SKILL.md`, which the user
starts by picking an item. Producing a list of plausible-looking "safe"
judgements that nobody verified is the failure this project exists to
prevent.
