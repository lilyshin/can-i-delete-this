<!-- 한국어로 작성하셔도 됩니다. Korean or English both welcome. -->

**What does this change?**

**Which test proves it?**

This project is fixture-driven: a new noise category or a new blame trap
needs a fixture under `tests/fixtures/make_fixture_repo.py` and a regression
test, not just a prose explanation. See `CONTRIBUTING.md`.

**Checklist**

- [ ] `python3 -m unittest discover -s tests -v` passes
- [ ] No new external dependency (standard library only)
- [ ] `SKILL.md` still reads end to end in under 500 lines, if touched
- [ ] No unresolved placeholder markers left in shipped files
