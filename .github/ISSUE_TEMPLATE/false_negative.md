---
name: Noise false negative or false positive
about: A commit was scored is_noise wrong, or a real introducing commit was missed
labels: noise-catalog
---

**Which noise category, if any, applies?**

See `skills/can-i-delete-this/noise-catalog.md` (N1-N11). If this does not fit
any existing category, say so; it may be a new one.

**The commit and why the current score is wrong**

Subject, sha (or a sanitized equivalent), and what `noise.score` returned vs.
what it should have returned.

**Repro**

A fixture-style script (see `tests/fixtures/make_fixture_repo.py`) is the
most actionable form. A pasted diff is the next best thing.
