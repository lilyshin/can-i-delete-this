# Pressure tests

These are prompts, not code. Run each against a subagent that does NOT have
the skill loaded to record the baseline, then again with the skill loaded.

Record results in each file under `## Observed`.

The premise: if you never watched an agent fail without the skill, you do not
know whether the skill teaches the right thing.

## Status of this round

`SKILL.md` does not exist yet (Task 10 writes it). Every scenario below was
therefore run in its "no skill loaded" form only, including the two files
whose prompt text says "with the skill loaded": there is nothing to load yet,
so that phrase describes how the same prompt should be re-run once Task 10
lands, not what was actually observed here. The `## Observed` sections in
every file in this directory record a genuine baseline run, not a
skill-equipped run.

## Fixtures

Fixture repositories are built outside this project, under `/tmp`, using
this project's `tests/fixtures/make_fixture_repo.py`:

- F1 (`build_f1`) at `/tmp/cidt-baseline/f1`: used by `baseline.md` and
  `pressure-shallow.md`. A token-level formatter commit touching 25 files
  buries a 2019 hotfix (`hotfix: prevent double charge (#4127)`) behind a
  2023 `chore: apply formatter` commit that `git blame` reports directly.
- F4 (`build_f4`) at `/tmp/cidt-guess/f4`: used by `pressure-guess.md`. A
  single squash commit is both the real change and the noise; the honest
  answer here is "inconclusive", not a coin-flip `safe`/`danger`.
- F5 (`build_f5`), a revert-then-reintroduce fixture, is referenced in this
  project's design docs as the strongest "do not delete" signal but is not
  used by any file in this directory; no scenario here currently exercises
  it.
- Deep history (`build_deep_history`) at `/tmp/cidt-deep/deep_history`: used
  by `pressure-truncate.md`, added after code review found the file's
  original design could not test what it claimed to. 113 real commits touch
  one file: a real fix early on (`fix: reject replayed session tokens after
  logout (#5521)`), 110 filler commits, and a final formatter commit that
  touches the same line, so a single `git blame` call reports only the
  formatter commit. Unlike F1's 3-commit history, reading "everything" here
  is a genuinely large task, which is the point: F1 alone did not create
  enough cost to tempt an agent into stopping early (see `baseline.md`'s
  negative result), so this fixture exists to make that temptation real.

`pressure-truncate.md`'s superseded design (kept in that file for the
record) did not use a fixture repository: it ran this project's own
`trace.py` directly and handed the resulting JSON, verbatim, to a subagent
that never saw a repository at all. That tested whether an agent reads a
labeled `"truncated": true` field back correctly, not whether it notices
and discloses stopping its own investigation early, so it could not
produce evidence about the failure mode this scenario is meant to test.
The current design uses the deep-history fixture above instead, giving the
agent a real repository and no tool output at all.

## Contamination control

Every subagent in this directory, across every scenario including the
redesigned `pressure-truncate.md`, was given a working directory inside a
fixture repo (under `/tmp`, never inside this project) and only the
user-style question. They were never told this project exists, never shown
`trace.py`, `noise.py`, `gitq.py`, or any term from this project's
vocabulary (pickaxe, noise classification, blame trap, N1/N4/...). Each
fixture directory was independently checked with `find` before any agent
was dispatched into it, confirming it contains only the fixture's own
files and `.git`, nothing that points back at this project.
