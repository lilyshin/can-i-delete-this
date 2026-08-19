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
- **No script edits the code under investigation, and none runs `git apply`.**
  `gitq.py` only runs read-only git subcommands: `blame`, `log`, `show`, `diff`, `rev-parse`,
  `rev-list`, `cat-file`, `ls-files`, `ls-tree`, `merge-base`, `name-rev`,
  `describe`, `for-each-ref`, `shortlog`, `var`, `grep` (`rev-list` is
  allowed but not actually called by any production code path today; `grep`
  searches the working tree only, used to judge needle rarity). Do not add a
  write path there, and do not add `Write` to any plugin manifest's
  `capabilities`. Two scripts do write a file, and a new one needs the same
  justification: `render.py` writes the HTML report (system temp directory
  by default, or wherever `--outdir` points), and `patch.py --out` writes a
  patch at the path the user named, refusing when that path is the file
  under investigation.
- **A denylisted flag is not the only guard against a git subprocess
  running an external program on our behalf.** `WRITE_FLAG_PREFIXES`
  refuses known write-adjacent flags (including short forms, e.g. `-O` for
  `--open-files-in-pager`), but `run_git` also forces `-c core.pager=cat`,
  `-c diff.external=`, and a set of environment variables
  (`GIT_PAGER`/`PAGER`/`GIT_EXTERNAL_DIFF`/`GIT_EDITOR`/
  `GIT_SEQUENCE_EDITOR`/`GIT_ASKPASS`/`SSH_ASKPASS`) onto every invocation,
  so that a repo's own config or the ambient environment cannot name a
  program to exec even through a flag this project has not thought of. If
  you add a new subcommand or flag to `gitq.py`, check by hand (or ask:
  "does git ever launch an external program for this, via a flag, a
  config key, or an environment variable, regardless of whether stdout is
  a terminal?") before assuming the existing guards cover it, the way
  `-O` did not until this was found. Never add `GIT_CONFIG_GLOBAL` or
  `GIT_CONFIG_SYSTEM` to the environment overrides: respecting the
  caller's own git config when reading the caller's own repository is
  intentional.
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

- **Shipped documentation stays in English**: `SKILL.md` is read by an
  agent on every invocation and the reference docs alongside it serve the
  same audience, so the files this project ships keep one language. The
  exceptions that already exist stay: README.md's "🇰🇷 한국어로 읽기" block
  and the verbatim quotes preserved in `tests/pressure/`.
- **Everything you submit can be in Korean or English, whichever you
  write faster.** Issues, PR descriptions, review comments, commit
  messages: 🇰🇷 한국어로 쓰셔도 됩니다. 오히려 좋습니다 (the maintainer
  reads Korean first). The existing commit history uses English subjects with
  Korean bodies; matching that is appreciated but a fully Korean commit
  message will not get a PR rejected.
