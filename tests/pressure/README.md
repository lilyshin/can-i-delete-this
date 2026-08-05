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

`pressure-truncate.md` does not use a fixture repository. It runs this
project's own `trace.py` directly (the brief specifies the exact command)
and hands the resulting JSON, verbatim, to a subagent that never sees a
repository at all, so there is nothing for it to wander into.

## Contamination control

Baseline and pressure-shallow/pressure-guess subagents were given a working
directory inside the fixture repo (under `/tmp`, never inside this project)
and only the user-style question. They were never told this project exists,
never shown `trace.py`, `noise.py`, `gitq.py`, or any term from this
project's vocabulary (pickaxe, noise classification, blame trap, N1/N4/...).
