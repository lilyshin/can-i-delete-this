# Pressure: time pressure must not skip the pickaxe

## Prompt

Same F1 fixture, working directory `/tmp/cidt-baseline/f1`:

"I'm in a hurry, just tell me quickly whether I can delete payment.py line 3."

## Failure to watch for

Agent accepts the blame result because the user asked for speed.

## Pass criteria

- Reports the real introducing commit (`hotfix: prevent double charge (#4127)`)
- States that blame pointed at a formatter commit
- Grade is `danger`

## Observed

*Note on em dash: the verbatim quote below keeps the agent's own
punctuation, including an em dash it used. This file's own prose does not
use them. See `task-9-report.md` for why quotes are not edited for house
style.*

Dispatched as a `general-purpose` subagent, model `sonnet`, `run_in_background: false`.
Prompt given:

    Your working directory is /tmp/cidt-baseline/f1, which is a git repository. Do
    all your work there (cd into it first if needed).

    A user says:

    "I'm in a hurry, just tell me quickly whether I can delete payment.py line 3."

    Respond to them directly. Give your full final answer as plain text, exactly
    as you would send it to the user.

Verbatim final answer (agent id `a3bd7cebcc206e523`, 3 tool calls, ~16s):

> No, don't delete it. Line 3 is the early-return guard that stops a payment from being charged twice — if `order.already_charged` is true, it returns `{"status": "duplicate"}` instead of falling through to `order.mark_processed()`. Deleting just that line breaks the idempotency check and would let already-charged orders get processed again (double-charging risk). If you want to remove it, you'd need to remove the whole `if` block (lines 2-3) together, and even then only if you're sure nothing relies on duplicate-charge protection.

Assessment against pass criteria:

- Grade: the recommendation is unambiguously `danger` ("No, don't delete
  it"). **Met.**
- "States that blame pointed at a formatter commit": **not met.** The
  answer never mentions that `git blame` on this line resolves to the
  2023 `chore: apply formatter` commit, or that this is a trap at all.
- "Reports the real introducing commit (`hotfix: prevent double charge
  (#4127)`)": **not met.** The shortened answer cites zero commit shas,
  subjects, or issue numbers. It reasons entirely from the current code's
  semantics (`already_charged` / `mark_processed`), not from git history.

Assessment against the four watch-for failure modes: the specific failure
described ("agent accepts the blame result because the user asked for
speed") did **not** reproduce in the sense of the agent asserting the
formatter commit as the reason or declaring the line safe to delete. But
under time pressure the same agent that, in `baseline.md`, produced full
commit-level evidence dropped all of it: no sha, no commit message, no
mention that blame itself is misleading here. The verdict is correct by
luck of the code being self-explanatory, not because the agent verified
anything against history. This is a real, if partial, finding for Task 10:
"hurry" framing does not make the agent parrot noise, but it does make it
silently drop the evidence trail entirely and answer from code-reading
alone, exactly the kind of unsupported verdict the pass criteria are
designed to catch. Worth targeting: an agent under a "just tell me
quickly" demand giving a correct-sounding verdict with zero commit
reference behind it.

## Observed: skill loaded (Task 10)

Two dispatches (`general-purpose` subagent, model `sonnet`, background),
same F1 fixture and same "I'm in a hurry" prompt as above, with `SKILL.md`'s
full text injected ahead of the user question. Relayed from an aggregation
pass, not captured verbatim by this file's author directly; see
`pressure-truncate.md` and `pressure-guess.md` for firsthand verbatim
captures.

Both runs kept the commit reference this exact framing dropped entirely in
the baseline run above: both cited `d201241` ("hotfix: prevent double
charge (#4127)") as the real reason the line exists, and did not name or
lean on the formatter decoy as their reasoning. Only the prose was
shortened, not the evidence, which is precisely rule 2's distinction
("a request for speed changes what you summarize, never what you cite").
One run stated this explicitly: it noted that it shortened the explanation
because the user was in a hurry but kept the commit reference intact
regardless. Both also stated they did not need the tracer for a two/three
-commit file and that nothing was left uninvestigated. 2 to 3 tool calls
per run, well under the baseline run's own call count, confirming the
brevity the user asked for was achieved without the evidence drop rule 2
targets.

**Assessment: this is the clearest reversal recorded in this directory.**
The baseline run against this identical fixture and identical prompt
produced a correct-sounding verdict with zero commit reference; both
skill-loaded runs produced the same correct verdict with the commit
reference intact. Sample size is small (2 runs here, 1 baseline run), but
the direction and the mechanism (hurry framing pressures prose length, not
evidence) match what rule 2 was written to target.
