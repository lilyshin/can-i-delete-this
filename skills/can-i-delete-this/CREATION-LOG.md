# Creation Log

Why this skill exists, what it deliberately does not do, and the three
times its own baseline testing or field use overturned an assumption the
design started with.
Read this before changing the scope of `SKILL.md`; it is the record of the
traps already found so nobody re-discovers them the slow way.

## Why this exists

`git blame` on a legacy codebase reliably points at whoever last reformatted
a line, not whoever wrote it for a reason. Developers hit this, get a
`chore: apply formatter` commit as the answer, and give up the investigation
right there. The gap is not a missing tool, it is a missing technique:
pickaxe search, line-lineage tracing, cross-file move detection, and
squash-history workarounds have to be combined by hand, and most people
doing archaeology on a file they do not own do not know to combine them.
This skill packages that technique, not a new capability.

## Rejected alternatives

- **Diagnostic report generator** (dump every commit touching a file into a
  formatted report and let the human read it). Rejected: this is what
  `git log -p` already does for free; a report adds ceremony without adding
  judgement. The value has to be in filtering noise and reaching a verdict,
  not in reformatting `log` output.
- **Code owner / domain expert finder** (who should I ask about this file).
  Rejected: crowded space already (several existing tools do exactly this),
  and it answers a different question than "can I delete this." Naming an
  owner is a byproduct this skill already gets for free from commit
  authorship; it does not need to be the product.
- **Code structure / dependency graph visualization**. Rejected: a different
  problem (understanding what calls what) from this skill's problem
  (understanding why a specific line exists). Visualizing structure would
  not have prevented a single blame-trap failure observed in this project's
  own pressure tests.

## Three value-proposition corrections

### Correction 1: `git blame -w` already defeats whitespace formatters on its own

The original F1 fixture was a formatter commit that only changed
indentation and blank lines. Once `gitq.py`'s blame invocation existed,
the fixture stopped being a trap: `blame -C -C -C` alone (no `-w`)
still returned the formatter commit, but `blame -w -C -C -C`, the invocation
this project actually ships, resolved straight through it to the real
introducing commit. The problem the fixture was built to catch was one git
had already solved. F1 was redesigned around a token-level
formatter instead, one that unifies quote style across the codebase, which
survives whitespace-ignoring diff because it is a content change, not a
whitespace change. That is the fixture this project ships today. Lesson:
verify a fixture actually traps the tool you are testing before trusting it,
because the tool may have already grown past the trap you designed.

### Correction 2: small histories do not need this skill at all

The first round of baseline testing ran an unaided agent, no skill loaded, against the
corrected F1 fixture (three commits total) with the plain question "why
does this line exist, can I delete it." It used `git blame` and
`git log --oneline --all`, correctly separated the 2023 formatter commit
from the 2019 hotfix, and cited both commit shas with subjects, twice,
independently. No amount of tooling improves on that. This directly produced
the "When you do not need this" section in `SKILL.md`: recommending
`git log -p` on a short history and stopping there is the correct outcome,
not a shortfall this skill needs to close. The skill's value only shows up
once a file's history is too large to read end to end, which the deep-history
fixture (113 commits) was built specifically to represent.

### Correction 3: the two paths should never have been mutually exclusive

0.2.1 was driven by a field report against a real repository, not a
pressure-test fixture: an agent asked about a file with two renames in its
history ran Correction 2's threshold check, `git log --oneline -- <path> |
wc -l`, got 4, and read the history directly instead of running the
tracer, exactly as `SKILL.md` instructed. The answer was correct. Two
things were still wrong. First, that command does not follow renames, so
it counted only commits touching the file's current path; the agent later
found the real count, with `--follow`, was 21, past the threshold that
should have sent it to the tracer instead. Second, and independent of the
miscount: the direct-reading path produced no report, no validated
verdict, and no HTML, because nothing in `SKILL.md` told an agent on that
path to produce them. The user's next question was "why is there no HTML?"

Correction 2 was right that a human reading a short history reaches a
better answer than ranked tooling output; it was wrong to make that a
reason to skip the tracer altogether, because the tracer is also what
produces every deliverable this skill promises. Fixed by decoupling the two
things the threshold was doing at once: it now decides only where an
agent's understanding of intent comes from (its own reading of `git log -p
--follow`, at or under twenty commits, versus the tracer's ranked
`introduction_candidates`, past it), never whether the tracer runs or
whether a report and artifact get produced. The tracer now always runs.
The threshold command was also fixed to include `--follow`, since the
miscount that triggered this correction was a real bug independent of the
restructuring.

That restructuring exposed a second, previously latent gap: a commit an
agent found by reading history directly, that the tracer's own searches
(blame, pickaxe, line-history) never surfaced at all, used to resolve
exactly like a stale or mistyped citation, an "unresolved" attribution
naming nothing. `citation.py` now accepts a commit evidence item's own
`subject`/`date`/`author` fields as a fallback source for exactly this
case; see `tests/test_citation_resolution.py`'s `TestHistoryReadCitation`
and `tests/test_trace_cases.py`'s `TestTwoRenames`.

## What the baseline observations actually concluded

Four failure modes were hypothesized before any testing (`docs/specs/`, not
shipped, not in this repo's public tree, section 10.2 of the original design
note): stopping at one `blame` call, promoting an unevidenced guess to a
grade, reading only a commit subject, and hiding a truncated search. That
first round of baseline testing tested all four against real fixtures and
a real agent, not against an imagined one:

1. **Stop at one `blame` call, read only the subject.** Did not reproduce on
   the plain "why does this exist" framing (`baseline.md`): the agent ran
   `blame` and `log`, and read full diff content, not just subject lines.
2. **Unevidenced grade promotion.** Reproduced, but only sometimes:
   `pressure-guess.md`'s forced yes/no framing against the squashed F4
   fixture produced a graded answer with zero commit reference in 1 of 5
   runs (20%); the other 4 investigated and cited the real squash commit
   before answering. Occasional, not default behavior.
3. **Hiding a truncated search.** The scenario built to test this directly
   (`pressure-truncate.md`'s first design) turned out to test something
   else: handing an agent JSON with a pre-labeled `"truncated": true` field
   and asking it to summarize that JSON tests field-reading, not whether an
   agent notices its own stopped investigation. That design could not
   produce evidence about the failure it was meant to catch, so it was
   rebuilt around a 113-commit fixture and a self-directed question with no
   tool output handed over. Under that redesign, a related but different
   failure did reproduce: one of three runs (`pressure-truncate.md`, run A)
   answered confidently after a single tool call with no disclosure that
   history was unchecked at all.
4. **A related, unanticipated failure surfaced unprompted**: one of the same
   three deep-history runs answered about the wrong line entirely (a
   build-marker comment instead of the security guard actually asked about),
   with full confidence and no sign it had mismatched the target. This is
   why `SKILL.md` rule 6 exists; it was not in the original four hypothesized
   failure modes, and it turned out to be worth a rule anyway because it
   showed up in the same run designed to test something else.

**The principle this produced: do not write a rule against a failure mode
that did not reproduce.** A rule that prevents a mistake the model does not
make costs context on every load and earns nothing. `SKILL.md`'s six rules
map onto observations 2, 3 (both the disclosure half and the hurried-answer
half seen in `pressure-shallow.md`), 4, plus the never-write-files and
respond-in-user's-language rules, which were not tested for failure at all
and are load-bearing for different reasons (safety and UX, not observed
agent error). Nothing in `SKILL.md` targets failure mode 1, because it did
not happen.

## A gap found by a later pressure re-run, not by the original baseline round

Re-running the pressure scenarios with `SKILL.md`'s text in force (the task
report describing exactly how "skill loaded" was approximated is not
shipped and not in this repo's public tree; the approximation itself is
described where it matters, in `tests/pressure/pressure-truncate.md`'s
"Observed: skill loaded" section: the subagent was given `SKILL.md`'s full
text inline and told the skill's scripts and reference docs exist on disk
at their real project paths, with permission to read or run them) surfaced
a document gap
`SKILL.md` did not originally cover: two independent runs against the same
F4 fixture (squashed history, commit `16a76ec` is both the real change and
the only candidate) reached different answers by different, both
individually defensible, routes. One ran the tracer, which correctly scores
`16a76ec` as N10 noise (a squash commit's PR-title-shaped subject cannot be
trusted for intent) and reported `unknown`. Another skipped the tracer,
read `git log -p` directly, saw that `16a76ec`'s diff was in fact the real
change despite its untrustworthy subject, and reported `danger` with that
commit cited. The second answer is more useful, and nothing in the original
`SKILL.md` told an agent using the tracer to go check.

This was not a rule failing under pressure; it was a genuine blind spot in
the workflow, distinct in kind from the four hypothesized failure modes
above. `noise.py`'s conservative filtering is correct for what it is built
to do (do not trust a squash commit's message), but "excluded from
`introduction_candidates`" and "irrelevant to the target lines" are not the
same fact, and `SKILL.md` did not previously say so. Two things were added
in response, both documentation only, no scoring logic touched: a step in
`SKILL.md`'s workflow and `strategy-tree.md` instructing an agent to read a
noise-filtered commit's own diff with `git show` before settling for
`unknown`, and a concrete, checkable threshold (`git log --oneline | wc -l`,
twenty commits) in "When you do not need this" so two agents facing the
same short history no longer have a coin's chance of choosing different
paths. See `tests/pressure/pressure-guess.md`'s "Observed: skill loaded"
section for the fuller account, including the caveat that the three
skill-loaded runs recorded verbatim there all took the short-history path
and so did not, on their own, re-exercise the tracer-plus-diff-reading
route the fix targets.
