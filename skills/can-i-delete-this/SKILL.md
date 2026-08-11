---
name: can-i-delete-this
description: Use when the user asks whether some code can be deleted, why a line or block exists, or who introduced it, especially in a repository whose history is too large to read directly or when `git blame` returned a formatting or refactoring commit instead of a real answer. Traces the true introducing commit through formatter noise, renames, code moves and squashed history, then grades deletion risk with commit-level evidence. Triggers include "can I delete this", "why is this here", "what is this code for", "이 코드 지워도 되나", "이거 왜 있는 거지", "누가 넣었지".
---

# Can I Delete This

## What this does

`git blame` answers "who touched this line last", which is almost never the
question. This skill answers "why does this line exist, and what breaks if I
remove it", with commit references.

## The tracer always runs; the threshold decides how you read, not whether you report

Run `trace.py` on every request, regardless of history size. It is what
produces the report, the mechanically-checked evidence, and the artifact;
none of that exists on any path that skips it. What the history size
decides is where your own understanding of *why* the code exists comes
from, not whether the deliverables get made.

**Check history size first: `git log --oneline --follow -- <path> | wc -l`.**
Use `--follow`, not plain `-- <path>`: without it, the count only includes
commits that touched the file's *current* path, so a file that was ever
renamed comes back undercounted, sometimes drastically. A rename is exactly
the case where a short-looking history can be hiding a real introducing
commit further back, so this is not a corner case to shrug off; get the
count right before you decide anything from it.

- **Twenty commits or fewer:** in addition to running the tracer, read the
  whole thing yourself with `git log -p --follow -- <path>`, and let that
  reading, not the tracer's ranked candidates, drive your understanding of
  intent. We measured this: on a three-commit fixture, an agent with no
  skill loaded read the history directly, found the real introducing
  commit, dismissed the formatter commit, and cited its evidence correctly.
  At this size a human reading the actual diffs reaches a better answer
  than ranked output, and saying so plainly is correct, not a failure. Feed
  what you learn into the verdict; the tracer's JSON still supplies
  `render.py` and `artifacts.py` with the material they need to produce the
  report and the artifact.
- **Past twenty:** `log -p` stops fitting in a read end to end, so the
  tracer's `introduction_candidates` (already scored past noise) are your
  primary evidence instead of your own reading. (Twenty is a starting
  point, not a law; if a file's commits are unusually large or unusually
  terse, adjust by feel.)

Reach for the tracer's non-negotiable rules regardless of which of those two
you are in, and also when:

- `blame` lands on a formatter, rename or squash commit and you need the
  commit that actually introduced the code
- you need the answer in a fixed shape: a graded verdict, evidence that is
  mechanically checked, a report, and text to paste

**Every non-negotiable rule below applies on both paths.** Reading history
directly instead of leaning on the tracer's ranked candidates does not relax
the requirement to cite a commit, name the target, leave the user's files
untouched, produce a report, or answer in the user's language; it only
changes which reading produces your understanding of intent. If the commit
you found by your own reading never showed up in `introduction_candidates`
or `blame_candidates` (this can happen: a rename bundled with unrelated
changes can defeat blame's own move detection, past what pickaxe's
current-content needles can recover), **do not cite it from memory.**
Re-run the tracer with `--include-commit <sha>` (repeatable) before you
write the verdict; it looks the sha up against the repository with
`gitq.commit_meta` and, once verified, adds it to `introduction_candidates`
with `why: "cited"`. Only a commit `trace.py` itself has confirmed exists,
with subject/date/author it read from git, may ever be cited as evidence;
a subject you remember or paraphrase from your own reading is not a
substitute; asking the tracer to verify it costs one more short run at this
history size.

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
   follows the user, and that includes the two deliverables render.py and
   artifacts.py produce, not only your own prose. Pass `--lang` to both
   (see step 8): `--lang ko` for a Korean user, and so on. The default is
   English (`en`); an unsupported value falls back to English rather than
   erroring. `render.py`/`artifacts.py` only translate their own chrome
   (badge labels, card headers, the dot legend, the artifact wording); the
   data inside it, shas, paths, commit subjects, author names, dates, is
   never translated and always comes from git, regardless of `--lang`.
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
6. If step 5 (or your own reading of a short history, per the section
   above) points at a commit that is not already in `introduction_candidates`
   or `blame_candidates`, re-run the tracer once more with
   `--include-commit <sha>` (repeatable for more than one) before you write
   the verdict, so it gets verified against the repository and added with
   `why: "cited"`. Do not skip this and cite a remembered sha directly: the
   tracer confirms the sha exists and reads its real subject/date/author
   from git, which is the whole reason a citation is trustworthy at all.
7. Write the verdict JSON (schema in scripts/verdict.py) and validate it.
8. Render and hand over, passing `--lang` to match the language you are
   answering in (default `en`; omit it for an English-speaking user):

   ```
   python3 <skill>/scripts/render.py --trace t.json --verdict v.json --lang ko
   python3 <skill>/scripts/artifacts.py --trace t.json --verdict v.json --copy --lang ko
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
