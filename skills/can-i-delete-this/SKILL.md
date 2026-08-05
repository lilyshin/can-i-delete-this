---
name: can-i-delete-this
description: Use when the user asks whether some code can be deleted, why a line or block exists, or who introduced it, especially in a repository whose history is too large to read directly or when `git blame` returned a formatting or refactoring commit instead of a real answer. Traces the true introducing commit through formatter noise, renames, code moves and squashed history, then grades deletion risk with commit-level evidence. Triggers include "can I delete this", "why is this here", "what is this code for", "이 코드 지워도 되나", "이거 왜 있는 거지", "누가 넣었지".
---

# Can I Delete This

## What this does

`git blame` answers "who touched this line last", which is almost never the
question. This skill answers "why does this line exist, and what breaks if I
remove it", with commit references.

## When you do not need this

**Check history size first: `git log --oneline -- <path> | wc -l`.** Twenty
commits or fewer, read the whole thing with `git log -p --follow -- <path>`
instead of running the tracer; you will reach the right answer faster than
any tooling. We measured this: on a three-commit fixture, an agent with no
skill loaded found the real introducing commit, dismissed the formatter
commit, and cited its evidence correctly. Past twenty, `log -p` stops fitting
in a read end to end, and that is where the tracer earns its keep. (Twenty is
a starting point, not a law; if a file's commits are unusually large or
unusually terse, adjust by feel.)

Run the tracer once the count above crosses the threshold, or when:

- `blame` lands on a formatter, rename or squash commit and you need the
  commit that actually introduced the code
- you need the answer in a fixed shape: a graded verdict, evidence that is
  mechanically checked, a report, and text to paste

**Every non-negotiable rule below applies on both paths.** Reading history
directly instead of running the tracer does not relax the requirement to
cite a commit, name the target, leave the user's files untouched, or answer
in the user's language; it only changes which command produces the evidence.

Say so plainly when the history is small. Recommending `git log -p` instead of
running the tracer is a correct outcome, not a failure.

## Non-negotiable rules

1. **Never grade above `unknown` without a commit reference.** Run
   `verdict.py` on your verdict before showing it. If it fails, fix the
   verdict, not the validator.
2. **A request for speed changes what you summarize, never what you cite.**
   Under a hurry framing an agent tends to keep the conclusion and drop the
   commit references behind it. That is the failure we observed. Shorten the
   prose, keep the evidence.
3. **Always disclose what you did not search.** If `limits.truncated` or
   `limits.candidate_cap_reached` is true, say so in the user-facing summary
   and offer to rerun with a higher limit. The tool reports this to you; you
   are the one who must pass it on.
4. **Never write to the user's files.** No comment injection, no PR creation.
   Produce text; the user decides.
5. **Respond in the user's language.** This file is English; your output
   follows the user.
6. **Name the target you answered about.** Quote `target` from the tracer's
   output back to the user: path, and the line range. We watched an agent
   answer confidently about a different line than the one it was asked
   about, and recommend deleting it. Nothing in its answer revealed the
   mismatch. If you cannot resolve the target unambiguously, say so instead
   of guessing which line was meant.

## Workflow

1. Resolve the target: file path and line range. If the user pasted a
   snippet, locate it with `grep -n` first.
2. Run the tracer:

   ```
   python3 <skill>/scripts/trace.py --repo <repo> --file <path> --lines <start>:<end>
   ```

3. Read the JSON. `blame_candidates` marked `is_noise` are debris; see
   noise-catalog.md for what each category means.
4. If `introduction_candidates` is empty, follow strategy-tree.md before
   concluding anything. In particular: if every `blame_candidates` entry is
   noise and nothing else surfaced a candidate, do not stop at `unknown` yet.
   Read the noise commit's own diff with `git show <sha> -- <path>`. A
   commit is filtered as noise (a squash commit, N10, is the common case)
   because its *message* cannot be trusted for intent, not because its
   *diff* is unrelated to the target lines. If that diff is what actually
   added the target lines, it is the real introducing commit, and you may
   cite it even though `noise.py` flagged it.
5. Recover intent. Commit subjects are usually useless. Prefer, in order:
   tests added in the same commit, the PR body, linked issues, adjacent
   comments.
6. Write the verdict JSON (schema in scripts/verdict.py) and validate it.
7. Render and hand over:

   ```
   python3 <skill>/scripts/render.py --trace t.json --verdict v.json
   python3 <skill>/scripts/artifacts.py --trace t.json --verdict v.json --copy
   ```

## Grading

| Grade | Use when |
|---|---|
| `danger` | Introduced by a hotfix, incident, or revert chain, or a test guards it |
| `conditional` | The reason was time-bound (a version, platform, migration). List the conditions |
| `safe` | The reason demonstrably no longer applies |
| `unknown` | You could not find evidence. This is a valid answer |

A `danger` verdict with no guarding test must say so and propose the
regression test to add first.

## Reference

- noise-catalog.md: the eleven debris categories and how to route around each
- strategy-tree.md: what to do when the obvious path comes up empty
