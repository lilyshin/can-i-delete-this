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
7. **Read every candidate's subject yourself, in whatever language it is
   written, and treat `hints` as claims rather than findings.** The tracer
   filters a commit only on what it changed: the diff, the paths, the
   commit graph (`noise.signals`, and `is_noise` follows from those alone).
   Vocabulary in the subject is reported separately as `noise.hints`,
   because a regex that reads subjects works in one language and silently
   fails in every other, and because a commit saying `chore: apply
   formatter` while changing a timeout value is lying to you. You are the
   part of this pipeline that reads human language, all of it, so a
   Japanese subject or a bare `cleanup` is yours to interpret and no
   tooling has pre-judged it for you. Two consequences to expect:
   candidate lists are slightly longer than they would be under
   subject-filtering, and a commit carrying a hint like `PR-title shaped
   subject over 310 files` is still a candidate you must judge by its
   diff, not one already dismissed.

## Workflow

1. Resolve the target: file path and line range. If the user pasted a
   snippet, locate it with `grep -n` first. If you were invoked via the
   `/can-i-delete-this:check` command, the target is already resolved and
   confirmed; it arrives as `path:start-end` in your input, so skip
   straight to step 2.
2. Run the tracer:

   ```
   python3 <skill>/scripts/trace.py --repo <repo> --file <path> --lines <start>:<end>
   ```

3. Read the JSON. `blame_candidates` marked `is_noise` are debris on the
   evidence of their diff, paths or parent count; `noise.hints` alongside
   them are claims made by the subject line and dismiss nothing (rule 7).
   See noise-catalog.md for what each category means.
4. If `introduction_candidates` is empty, follow strategy-tree.md before
   concluding anything. In particular: if every `blame_candidates` entry is
   noise and nothing else surfaced a candidate, do not stop at `unknown`
   yet. Read the noise commit's own diff with `git show <sha> -- <path>`.
   A commit is filtered because of what its diff looked like *across the
   whole commit* (a merge, a vendored dump, a cosmetic rewrite), which is
   not the same fact as "its diff is unrelated to the target lines". If
   that diff is what actually added the target lines, it is the real
   introducing commit, and you may cite it even though `noise.py` flagged
   it.
5. Recover intent. Commit subjects are usually useless on their own, so
   every candidate carries its `body` (capped at 600 characters, with
   `body_truncated` set when it was cut, in which case `git show <sha>`
   has the rest). Read it: `fix: guard charge` grades nothing, while its
   body naming the incident and the ticket grades `danger`. Then prefer,
   in order: tests added in the same commit, the PR body, linked issues,
   adjacent comments.
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

   For a `danger` verdict only, you may also offer the keep-comment as a
   patch instead of text the user pastes by hand:

   ```
   python3 <skill>/scripts/patch.py --trace t.json --verdict v.json --lang ko
   ```

   Hand the patch to the user; do not run `git apply` yourself. `patch.py`
   only writes the diff, to stdout or to `--out`; it never opens the target
   file for writing and never applies the patch. It inserts the verdict's own
   `artifact.content`, so the patch and the text above carry one comment, not
   two. It refuses instead of guessing when the file on disk has moved since
   the trace or the target's language has no known comment marker; see
   `patch.py` for the full list of refusals. On a refusal, do not work around
   it: hand over the plain-text keep-comment `artifacts.py` printed in this
   same step and let the user paste it, and pass on the refusal's own
   sentence, which says what would make a patch possible.

## Scanning instead of asking about one line

The workflow above starts from a target the user already suspects. When
they have no particular line in mind and want to know what is worth asking
about, `scripts/scan.py` finds blocks of commented-out code under a path
and attaches the commit that commented each one out. It grades nothing, so
a scan is not an answer: the user picks an item and that item goes through
the workflow above unchanged. See batch-mode.md, and never call a scanned
block safe to delete without running that workflow on it.

## Grading

| Grade | Use when |
|---|---|
| `danger` | Introduced by a hotfix, incident, or revert chain, or a test guards it |
| `conditional` | Deleting is wrong *unless* some condition holds, and you cannot yet confirm it (the reason was time-bound: a version, platform, migration). List the conditions that must be verified before deleting |
| `safe` | The reason demonstrably no longer applies |
| `unknown` | You could not find evidence. This is a valid answer |

A `danger` verdict with no guarding test must say so and propose the
regression test to add first.

**A residual risk outside the current branch does not by itself make a
verdict `conditional`.** `conditional` means "deleting is wrong unless X
holds", a precondition to check before you delete. An unmerged branch that
still calls the code, and will fail to compile if it is ever merged
forward, is a consequence to disclose, not a precondition to check now:
nothing about today's delete decision changes while you wait to find out
whether that branch ever merges, and nothing you can verify today resolves
it either. That case stays whatever grade the evidence otherwise supports
(often `safe`), with the hazard recorded as a `risk`-role evidence item
(see the next paragraph) instead of being folded into `conditions`.

Evidence items may carry an optional `role` (schema in `scripts/verdict.py`,
`EVIDENCE_ROLES`): `introduced` and `superseded` tell the story of why the
code existed and what retired that reason, the strongest evidence for
`safe`; `guard` and `reference` record how isolated the code is today
(guarding tests/checks that argue against deleting, and mentions that do
not call it); `risk` records a hazard, like the unmerged branch above, that
survives the verdict regardless of grade. `role` is optional and additive;
an evidence item that omits it behaves exactly as it always has.

## Reference

- noise-catalog.md: the eleven debris categories, which of them filter (on
  diff evidence) versus only hint (on subject vocabulary), and how to route
  around each
- strategy-tree.md: what to do when the obvious path comes up empty
- batch-mode.md: scanning a directory for candidates instead of starting
  from one line, and what the scan deliberately does not decide
