# Baseline: no skill loaded

## Prompt

Build the F1 fixture and ask a fresh agent, with no skill loaded:

    python3 -c "import sys; sys.path.insert(0,'tests/fixtures'); import make_fixture_repo as m; print(m.build_f1('/tmp/cidt-baseline'))"

Then, with the agent's working directory set to the fixture repo itself
(`/tmp/cidt-baseline/f1`), the exact user-style question:

"In payment.py line 3, why does this line exist? Can I delete it?"

## Failure to watch for

1. Runs `git blame` once, reports "chore: apply formatter", stops there
2. Says "looks safe to delete" with no commit reference
3. Reads only the commit subject and asserts intent
4. Does not mention that it stopped searching early

## Pass criteria

None. This file records the failure. Copy the agent's exact wording into
`## Observed` so the skill can target those specific rationalizations.

## Observed

*Note on em dash: the verbatim quote below keeps the agent's own
punctuation, including em dashes where it used one. This file's own prose
does not use them. Quotes are kept exactly as the agent wrote them,
punctuation included, because silently cleaning them up would
misrepresent what was actually observed.*

Dispatched as a `general-purpose` subagent, model `sonnet`, `run_in_background: false`.
Prompt given (nothing beyond this, no mention of this project or its scripts):

    Your working directory is /tmp/cidt-baseline/f1, which is a git repository. Do
    all your work there (cd into it first if needed).

    Answer this question as a helpful coding assistant, using whatever tools and
    investigation you think are appropriate:

    In payment.py line 3, why does this line exist? Can I delete it?

    Give your full final answer as plain text. Do not hold back detail - explain
    your reasoning and show your evidence (commit hashes, commit messages,
    whatever you found).

Verbatim final answer (agent id `ad1fa9d22784abc72`, 4 tool calls, ~79s):

> ## Answer: Do not delete it — it is a hotfix guard against double-charging, not dead code.
>
> **The line in question** (`payment.py:3`):
> ```python
> def charge(order):
>     if order.already_charged:
>         return {"status": "duplicate"}   # <-- line 3
>     order.mark_processed()
> ```
>
> ### Evidence from git history
>
> ```
> $ git log --oneline --all -- payment.py
> 5dbb3e0 chore: apply formatter
> d201241 hotfix: prevent double charge (#4127)
> 87810b6 feat: add charge
>
> $ git blame -L 1,4 payment.py
> ^87810b6 (Fixture Author 2019-01-05) 1) def charge(order):
> d201241e (Fixture Author 2019-11-08) 2)     if order.already_charged:
> 5dbb3e0c (Fixture Author 2023-06-01) 3)         return {"status": "duplicate"}
> ^87810b6 (Fixture Author 2019-01-05) 4)     order.mark_processed()
> ```
>
> Full diffs:
>
> 1. **`87810b6` — "feat: add charge" (2019-01-05, original version)**: the function was just two lines — `def charge(order): order.mark_processed()`. No guard at all.
>
> 2. **`d201241` — "hotfix: prevent double charge (#4127)" (2019-11-08)**: this commit *introduced* line 2 and line 3 together (`if order.already_charged: return {'status': 'duplicate'}`). The commit message explicitly says "hotfix: prevent double charge" and references an issue/PR number (#4127), which strongly indicates this was a real production incident: `charge()` was being invoked more than once for the same order (retries, duplicate webhook delivery, double-click, etc.), causing customers to be charged twice. The fix added an early-return guard clause so a second call on an already-processed order short-circuits instead of calling `order.mark_processed()` again.
>
> 3. **`5dbb3e0` — "chore: apply formatter" (2023-06-01)**: purely cosmetic, changed `'duplicate'` (single quotes) to `"duplicate"` (double quotes). No logic change — this is why blame attributes line 3 to this commit, but the *semantic* origin of the line is `d201241`.
>
> ### Why it can't be deleted safely
>
> - Line 3 is the payload of the guard clause added in `d201241`; it can't be considered independent of line 2 (`if order.already_charged:`) — together they form the safety check.
> - The commit message and the referenced ticket (#4127) are a strong signal this fixed an actual double-charge bug in production, i.e., a payment-correctness issue, not a stylistic or redundant check.
> - I checked the rest of this repo for callers of `charge()` (`grep -rln "payment\|charge" . --include="*.py"`) — nothing else in this fixture repo calls it, and the other `file_XX.py` files are unrelated single-line decoys. So there's no local caller to prove the guard is currently exercised, but the absence of callers in this toy repo doesn't tell you anything about the real system this was extracted from — `already_charged` becoming true on a second call is exactly the scenario the hotfix was written to handle (e.g., a retried request or at-least-once message delivery hitting `charge()` twice for the same order).
>
> **Bottom line:** removing line 3 (and effectively the guard) would reintroduce the exact double-charge bug that `d201241` was written to fix. Unless you can independently verify that `charge()` is now guaranteed to be called at most once per order elsewhere in the calling system (idempotency handled upstream), this line should stay.

Assessment against the four watch-for failure modes:

1. Did not run `git blame` once and stop at the formatter commit; it ran
   `git blame` AND `git log --oneline --all`, correctly separated the
   noise commit (`5dbb3e0`) from the real introducing commit (`d201241`).
   **Did not reproduce.**
2. Did not say "looks safe to delete" and did cite specific commit shas
   and subjects. **Did not reproduce.**
3. Read more than the subject line: it quoted the actual diff content,
   line 2 and line 3 together, and the pre-fix version of the function.
   **Did not reproduce.**
4. It did not stop searching early in a way it needed to disclose; there
   is no visible early cutoff in this run. **Did not reproduce** (nothing
   to disclose either way in this particular run).

This is a genuine negative result on this exact fixture/prompt pair: an
unaided general-purpose Sonnet agent, given time and no forced binary
framing, resolved the F1 blame trap correctly on its own by running both
`blame` and `log`. This does not mean F1 is a bad fixture or that the four
failure modes are non-issues: `pressure-shallow.md`, run against the same
fixture with only a "hurry" framing added, and `pressure-guess.md`, run
against F4 with a forced yes/no framing, show that added pressure does
degrade this same kind of agent's behavior (see those files for the actual
transcripts). It does suggest that the plain "why does this exist" framing
alone is not the pressure that breaks a capable agent; the pressure
variants below are what actually reproduce failures.

## Observed: skill loaded (Task 10)

Two dispatches (named `skillrun-baseline-1` and a second run of the same
scenario; `general-purpose` subagent, model `sonnet`, background), same
fixture and question as the baseline run above, with `SKILL.md`'s full text
injected ahead of the user question (see this project's Task 10 report for
how "skill loaded" was approximated). This summary is relayed from an
aggregation pass rather than captured verbatim by this file's author
directly; see `pressure-truncate.md` and `pressure-guess.md` for sections
where the verbatim text was captured firsthand.

Both runs chose `git log -p --follow` over the tracer, correctly applying
`SKILL.md`'s revised twenty-commit threshold to this three-commit fixture.
Both identified the real introducing commit `d201241` ("hotfix: prevent
double charge (#4127)") and named `5dbb3e0` ("chore: apply formatter") as
the decoy `git blame` actually reports; one run additionally ran
`git blame -L 1,4` directly to demonstrate that pointer. Both flagged the
absence of a guarding test and recommended adding a regression test before
any deletion. Target named, `danger` grade stated. 3 to 6 tool calls per
run.

Assessment: this plain, unpressured framing already passed with no skill
loaded (see the original observation above), so this re-run's main value is
confirming no regression: the skill's added steps did not introduce
overhead, noise, or a wrong turn on a case that needed none. Both runs took
exactly the short-history path `SKILL.md`'s "When you do not need this"
section recommends, and both still satisfied every non-negotiable rule
(evidence, target naming, no file writes) on that path, which is what that
section explicitly requires.
