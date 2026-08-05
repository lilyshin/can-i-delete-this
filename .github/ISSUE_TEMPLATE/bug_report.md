---
name: Bug report
about: Something in trace.py, noise.py, verdict.py, render.py or artifacts.py behaved wrong
labels: bug
---

**What did you run?**

The exact command, e.g. `python3 scripts/trace.py --repo . --file path --lines 3:5`.

**What did you expect, and what did you get?**

Include the JSON or HTML output if relevant.

**Can you share a minimal repro?**

A small `git init` script that reproduces the wrong noise category, missing
candidate, or wrong verdict is the fastest way to get this fixed. See
`tests/fixtures/make_fixture_repo.py` for the pattern this project uses.
