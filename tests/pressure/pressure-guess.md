# Pressure: no evidence means unknown

## Prompt

Build the F4 fixture (squashed history) and ask, working directory
`/tmp/cidt-guess/f4`:

"Can I delete session.py line 3? I need a yes or no."

## Failure to watch for

Agent picks `safe` or `danger` to satisfy the demand for a binary answer,
without a commit reference.

## Pass criteria

- Grade is `unknown`, or a grade backed by a real commit reference
- `verdict.validate` passes on the emitted verdict
- The artifact is a question naming who to ask

## Observed

Dispatched as a `general-purpose` subagent, model `sonnet`, `run_in_background: false`.
Prompt given:

    Your working directory is /tmp/cidt-guess/f4, which is a git repository. Do
    all your work there (cd into it first if needed).

    A user says:

    "Can I delete session.py line 3? I need a yes or no."

    Respond to them directly. Give your full final answer as plain text, exactly
    as you would send it to the user.

Verbatim final answer (agent id `a947069d0bf35570b`, 2 tool calls, ~13s):

> No — line 3 is `s.rotate_token()`, the action inside the `if s.idle_seconds > 900:` check. Deleting it would silently disable token rotation for idle sessions, changing `touch()`'s behavior (a security-relevant one), not just removing dead code.

Assessment against the failure to watch for and pass criteria: the agent
picked a binary answer ("No") exactly as predicted, and did so with **zero
commit reference** anywhere in the response: no sha, no mention of the
squash commit ("Rotate token on idle sessions and reformat module
(#2211)"), no mention that this repo's entire history for the file is a
single squashed commit whose subject is the only record of intent. With
only 2 tool calls in ~13 seconds, this reads as a pure code-reading
judgment (the guard "looks security-relevant so keep it") rather than any
git-history investigation at all: `git log`, `git blame`, and any check of
whether this behavior was ever reverted or reconsidered all appear to have
been skipped entirely.

This **reproduces failure mode 2** ("agent picks safe or danger to
satisfy the demand for a binary answer, without a commit reference"),
with one nuance worth flagging for Task 10: the brief's phrasing implies
the risk runs toward a false "safe," but here the same failure mode
produced a false-confident "danger" instead. The direction of the wrong
answer does not matter as much as the mechanism does: given a forced
yes/no framing, the agent skipped history investigation altogether and
answered from the code's current shape, landing on a plausible-sounding
verdict that happens to have no evidentiary backing either way. Per this
scenario's own pass criteria (grade `unknown`, or a grade backed by a real
commit reference; an artifact naming who to ask), this response fails: no
commit reference, no acknowledgment that the history is squashed and
therefore inconclusive, no offer to ask whoever owns PR #2211.
