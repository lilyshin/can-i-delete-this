# Contributing

## Ground rules

- **Python 3.9+ standard library only.** No third-party dependency, ever.
  This is what keeps the skill installable with nothing but `python3` on
  PATH.
- **Every claim needs a fixture.** If you add a noise category or a new
  blame trap, add it under `tests/fixtures/make_fixture_repo.py` and write a
  regression test against it. A prose description of a bug is a bug report;
  a fixture that reproduces it is a fix waiting to be written. See
  `skills/can-i-delete-this/CREATION-LOG.md` for two cases where this
  project's own untested assumptions turned out to be wrong once a fixture
  was built.
- **This skill never writes to the user's repository.** `gitq.py` only runs
  read-only git subcommands: `blame`, `log`, `show`, `diff`, `rev-parse`,
  `rev-list`, `cat-file`, `ls-files`, `ls-tree`, `merge-base`, `name-rev`,
  `describe`, `for-each-ref`, `shortlog`, `var` (`rev-list` is allowed but
  not actually called by any production code path today). Do not add a
  write path, and do not add `Write` to any plugin manifest's
  `capabilities`.
- **No em dash characters** in any file. Use a comma, a period, or
  parentheses instead.

## Running the tests

    python3 -m unittest discover -s tests -v

Fixture builders (`tests/fixtures/make_fixture_repo.py`) create throwaway
git repositories on disk and run real git commands against them, so tests
need a working `git` on PATH with a usable identity:

    git config --global user.email you@example.com
    git config --global user.name "Your Name"

## Adding a noise category

1. Write the fixture first: a small script that builds a repo where `git
   blame` gives the wrong answer for a specific, nameable reason.
2. Confirm the fixture actually traps the current code (run `trace.py`
   against it before touching `noise.py`). `CREATION-LOG.md`'s first
   correction exists because a fixture was trusted without this check.
3. Add the structural or keyword signal to `noise.py`, plus a unit test.
4. Document the category in `skills/can-i-delete-this/noise-catalog.md`
   with its signals, how to route around it, and which fixture proves it.

## SKILL.md changes

`SKILL.md` is read on every invocation, so it stays under 500 lines and
only states rules that were shown to matter against a real pressure test.
Do not add a rule for a failure mode you have not observed; see
`CREATION-LOG.md`'s closing section for the principle and its cost.

## Style

- Documentation in English. `docs/specs/` (not shipped, not in this repo's
  public tree) is the only place Korean-only notes belong.
- Commit subjects in English.
