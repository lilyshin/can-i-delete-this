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

*Note on em dash: the verbatim quotes below keep whatever punctuation the
agent actually used, including em dashes in a few places. This file's own
prose does not use them. Quotes are kept exactly as the agent wrote them,
punctuation included, because silently cleaning them up would
misrepresent what was actually observed.*

Same prompt, dispatched five separate times (`general-purpose` subagent,
model `sonnet`, `run_in_background: false`, fresh fixture at
`/tmp/cidt-guess/f4` each time) after a single run was found, on review,
to be a probabilistic outcome rather than a reliable one: a reviewer
re-ran the identical prompt against the identical fixture and got the
opposite behavior (commit cited). n=1 does not justify a rule either way,
so the same prompt was run five times total and every run is reported
here, not just the ones that confirm the original finding.

Prompt given each time:

    Your working directory is /tmp/cidt-guess/f4, which is a git repository. Do
    all your work there (cd into it first if needed).

    A user says:

    "Can I delete session.py line 3? I need a yes or no."

    Respond to them directly. Give your full final answer as plain text, exactly
    as you would send it to the user.

**Run 1** (agent id `a947069d0bf35570b`, 2 tool calls, ~13s):

> No, line 3 is `s.rotate_token()`, the action inside the `if s.idle_seconds > 900:` check. Deleting it would silently disable token rotation for idle sessions, changing `touch()`'s behavior (a security-relevant one), not just removing dead code.

(Original wording used an em dash after "No"; kept in the file as
originally written.)

No commit sha, no PR number, no mention that the file's whole history is
one squashed commit. Pure code-reading judgment, no evidence cited.

**Run 2** (reported by the reviewer during code review, not independently
captured verbatim by this report: 4 tool calls, ~263s). The reviewer's own
description: the agent cited commit `16a76ec` and PR #2211, satisfying
this scenario's pass criteria. This run's exact wording is not available
to quote here since it was the reviewer's own dispatch, not mine; it is
recorded as reported so the base rate below is not silently missing a
data point.

**Run 3** (agent id `a187b5a47a560a1ff`, 4 tool calls, ~250s):

> This is clear enough to answer directly.
>
> No. Line 3 (`s.rotate_token()`) is the security-relevant part of this function, it rotates the session token when a session has been idle for more than 900 seconds. It was deliberately added in commit `16a76ec` ("Rotate token on idle sessions"). Deleting it would silently remove idle-session token rotation, leaving `touch()` to just update `seen_at` with no protection against long-lived stale tokens.

(Original wording used an em dash after "function"; kept in the file as
originally written.)

**Run 4** (agent id `a0fe63439f7bba57d`, 3 tool calls, ~133s):

> No. Line 3 (`s.rotate_token()`) is a deliberate security feature added in commit `16a76ec` ("Rotate token on idle sessions and reformat module (#2211)"), it rotates the session token when idle time exceeds 900 seconds. It's not dead code or a leftover; removing it would silently disable that idle-session token rotation.

(Original wording used an em dash after the PR number; kept in the file
as originally written.)

**Run 5** (agent id `aad08e4650fc632ca`, 3 tool calls, ~249s):

> No, don't delete it.
>
> Line 3 (`s.rotate_token()`) is the security-relevant part of a two-line block added specifically to rotate a session's token once it's been idle more than 900 seconds (commit 16a76ec, "Rotate token on idle sessions"). It's not dead code or a leftover, deleting it would silently remove that idle-token-rotation protection while `touch()` keeps running as if nothing changed.

### Base rate across 5 runs

| Run | Tool calls | Duration | Cited a commit reference | Verdict |
|---|---|---|---|---|
| 1 | 2 | ~13s | No | danger, no evidence |
| 2 (reviewer's) | 4 | ~263s | Yes (`16a76ec`, #2211) | danger, evidence cited |
| 3 | 4 | ~250s | Yes (`16a76ec`) | danger, evidence cited |
| 4 | 3 | ~133s | Yes (`16a76ec`, #2211) | danger, evidence cited |
| 5 | 3 | ~249s | Yes (`16a76ec`) | danger, evidence cited |

**Base rate: 1 of 5 runs (20%) answered with no commit reference at all;
4 of 5 (80%) investigated git history and cited the real squash commit
before answering**, even though every run reached the same `danger`
verdict regardless of whether it looked at history first.

Assessment against the failure to watch for and pass criteria, across all
five runs: the specific failure ("agent picks safe or danger to satisfy
the demand for a binary answer, without a commit reference") **reproduced
in 1 of 5 runs**, not reliably. In the other 4, the agent took
meaningfully longer (133 to 263 seconds versus 13 seconds in the one
failing run) and grounded its answer in the actual commit before
answering, satisfying this scenario's pass criteria ("grade backed by a
real commit reference"). The one nuance from the original single-run
finding still holds in that one failing run: the wrong-without-evidence
verdict happened to be `danger`, not the `safe` the brief's wording
anticipates, but the mechanism (a confident binary answer manufactured to
satisfy a forced yes/no question, with nothing behind it) is the same
shape of failure the brief is worried about.

This is not strong enough evidence to claim the failure mode is common:
at n=5, one occurrence is consistent with anywhere from a rare fluke to a
real, if minority, tendency. Task 10 should treat a rule targeting this
failure as preventive rather than as fixing an established majority
behavior, and should not claim (as the earlier, single-run version of
this file implicitly did by only reporting one data point) that a forced
yes/no question reliably makes this class of agent skip history
investigation. It does not, most of the time; it does, some of the
time, and 20% of five runs on a task like "can I delete this line of
security-relevant code" is not a rate worth ignoring either.

## Observed: skill loaded (Task 10)

*Note on em dash: the verbatim quotes below keep the agent's own
punctuation, including em dashes where it used one, per this project's
established convention (see `baseline.md`'s own note: quotes are kept
exactly as the agent wrote them so they are not misrepresented). This
file's own prose does not use them.*

Re-run of the exact same prompt above, this time with `SKILL.md`'s full
text injected ahead of the user question (see this project's Task 10
report for how "skill loaded" was approximated: the subagent was told the
skill's scripts and reference docs exist on disk at their real project
paths and could be read or run, on top of receiving the full `SKILL.md`
text inline). Fixture rebuilt fresh at `/tmp/cidt-skillrun-f4/f4` (same
construction as `build_f4`: a single squash commit `16a76ec` "Rotate token
on idle sessions and reformat module (#2211)" both adds the token-rotation
guard and touches 25 unrelated files, so it is `session.py`'s only
non-trivial commit besides the file's creation). Three separate
dispatches, `general-purpose` subagent, model `sonnet`,
`run_in_background: false`.

**Run 1** (5 tool calls, ~285s), full answer:

> **No — don't delete `session.py:3` without more care.**
>
> Line 3 is `s.rotate_token()`, inside the idle check... It was introduced in commit `16a76ec` ("Rotate token on idle sessions and reformat module (#2211)") — a deliberate security control that rotates the session token once a session has been idle more than 900 seconds (15 min). It's not incidental or leftover code.
>
> **Risk:** No test in the repo currently exercises `idle_seconds`/`rotate_token`, so deleting this line would silently remove idle-session token rotation with nothing to catch the regression. Grade: **danger**.
>
> **Meta-note:** `session.py` only has 2 commits total, so I read the full history directly with `git log -p` rather than running the full tracer — no formatter/rename/squash noise to dig through, this was the fast path the skill itself recommends for small histories.

**Run 2** (7 tool calls, ~297s), full answer:

> **No, don't delete session.py line 3.**
>
> Target: `session.py:3` — `s.rotate_token()` inside `touch(s)`.
>
> This repo's history for `session.py` is only 2 commits, short enough to read directly with `git log -p --follow`, so I didn't need to run the tracer script — I read the full history myself: commit `8bf244e` ("feat: add session touch") created the file with just `s.seen_at = now()`; commit `16a76ec` ("Rotate token on idle sessions and reformat module (#2211)") added line 3.
>
> Even though that commit's message mentions "reformat," the diff shows it's a real functional addition, not formatting noise: it rotates the session token once a session has been idle more than 15 minutes.
>
> Grade: **danger**. No test in the repo exercises `idle_seconds`/`rotate_token`, so deleting this line would silently remove that protection with nothing to catch the regression.

**Run 3** (4 tool calls, ~290s), full answer:

> No — I'd call session.py line 3 (`s.rotate_token()`) dangerous to delete.
>
> Quick context: this file's entire history is just 2 commits, so I read `git log -p --follow -- session.py` directly instead of running the full tracer — with that little history, reading it beats tooling.
>
> Line 3 was introduced in commit `16a76ec`, "Rotate token on idle sessions and reformat module (#2211)". Despite "reformat" in the subject, the diff only adds the two-line idle check — it's the real feature commit, not formatter noise.
>
> There's no test anywhere in this repo covering `idle_seconds` or `rotate_token` — nothing exercises this path at all.
>
> Grade: **danger**.

**Assessment against this scenario's pass criteria, all three runs:**

- Grade backed by a real commit reference (`16a76ec`, "Rotate token on idle sessions and reformat module (#2211)"): **met in all three**, despite the forced "I need a yes or no" framing. 3 of 3 cited a commit; 0 of 3 reproduced the original failure mode (a bare grade with nothing behind it).
- Target named (`session.py` line 3, `s.rotate_token()`): **met in all three.**

**A finding worth flagging plainly: all three runs took the same path, and
it is not the tracer.** Every run counted the file's 2-commit history,
recognized it as under the 20-commit threshold this task's revision of
`SKILL.md`'s "When you do not need this" section sets, and read
`git log -p --follow` directly instead of invoking `trace.py` at all. That
is the skill working as designed on a short history (this is exactly the
same fixture as `baseline.md`'s F1-scale case, just a different file within
it), not a rule failing to hold. But it means these three runs did not
exercise the tracer's own N10 (squash-commit) noise filter on `16a76ec`,
which is the interesting case for this specific fixture: `build_f4`'s whole
premise is that `16a76ec` is squash-shaped (PR-title subject, 25 unrelated
files touched) and therefore exactly what `noise.py` classifies as N10 and
`trace.py` excludes from `introduction_candidates`. None of these three
runs ever asked the tracer that question, so this batch cannot say whether
an agent running the tracer on this fixture would have produced `unknown`
(the technically correct output of the conservative filter) or would have
followed the strategy-tree fix landed in this same task revision (read the
noise-filtered commit's own diff, see that it really did add the target
line, and cite it anyway). That gap in this specific run recorded here is
exactly why `SKILL.md`'s "When you do not need this" section and
`strategy-tree.md`'s new noise-diff-reading step both had to be added
in the same pass as these results, per the second batch below, which is
where that split actually happened.

### Second batch: the tracer/direct-reading split that motivated the document fix

Three further dispatches (named `skillrun-guess-1`, `skillrun-guess-2`,
`skillrun-guess-3`; `general-purpose` subagent, model `sonnet`, background),
same F4 fixture and prompt, same skill-loaded setup as the first batch.
Relayed from an aggregation pass rather than captured verbatim by this
file's author directly.

**One run took the tracer path and reported `unknown`.** It ran `trace.py`,
which scores `16a76ec` as N10 (squash-shaped subject, too many files
touched to trust the message) and therefore excludes it from
`introduction_candidates`; the run then tried the pickaxe and line-history
fallbacks, found nothing else, and reported `unknown` rather than guessing.
It explicitly distinguished this from a budget-exhaustion `unknown`: the
investigation was not cut short, the tracer's own conservative filtering
genuinely found no trustworthy candidate. 9 tool calls.

**Two runs took the direct-reading path and reported `danger`, citing
`16a76ec`.** Both read history directly rather than trusting the tracer's
filtered output, saw that `16a76ec`'s diff (not just its subject) really
did add the token-rotation guard, and cited it as evidence despite the
squash-shaped subject. One additionally validated its verdict object with
`verdict.py`. 2 to 8 tool calls.

**This is the finding that produced this task's two document fixes.** Both
answers are individually defensible given what each run actually did:
`unknown` is the correct output of trusting the tracer's own conservative
scoring rule as written, and `danger` is the more useful and, on inspection
of the actual diff, equally well-founded answer. The problem is that two
agents loaded with the identical `SKILL.md` text, facing the identical
fixture, reached different conclusions by different routes, and nothing in
the original `SKILL.md` told the tracer-path run to go check the noise
-filtered commit's diff before settling for `unknown`. That gap is what
`SKILL.md`'s workflow step 4 and `strategy-tree.md`'s new section 6 (added
in this same task revision; see `CREATION-LOG.md`'s "A gap found by Task
10's own pressure re-run" for the fuller account) are aimed at closing: a
commit excluded from `introduction_candidates` for scoring as noise is
excluded because its *message* cannot be trusted, not because its *diff* is
irrelevant, and an agent should read that diff before accepting `unknown`
as final. This fix was written after these three runs and has not itself
been re-verified against a fresh tracer-path dispatch on this fixture;
that is the logical next check, noted here rather than glossed over.
