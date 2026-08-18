# Batch Mode

`scan.py` answers a different question from `trace.py`. The tracer answers
"why does this line exist"; the scan answers "which lines should someone
ask that about". It grades nothing.

## What it looks for

One signal: a block of commented-out code, written either as a run of
consecutive line comments or as a `/* ... */` block comment. Either shape
answers to the same gates: `MIN_BLOCK_LINES` or longer, where the lines
that carry syntax prose would not also number `MIN_BLOCK_LINES` or more on
their own, and where that count is at least `CODE_SHAPE_RATIO` of the
non-blank comment lines. A run with enough blank comment lines mixed in
can pass the length and ratio gates while still falling short on that
middle count, and is dropped either way.

Block comments are scanned only for the extensions listed in
`scanner.BLOCK_MARKERS` (the C-family languages, plus SQL). A region
opened with `/**` is a doc comment and is discarded whole rather than
split into runs: a code-shaped usage example living inside a doc comment
is exactly the kind of comment nobody expects flagged, and it never
becomes a candidate.

That signal was chosen by measurement, not by taste. Against a 1710-file
Kotlin repository:

| Signal | Result |
|---|---|
| Unreferenced files, by filename | 240 candidates estimated, roughly 1 in 10 plausible |
| Unreferenced symbols | Needs a per-language adapter; a Python sample scored zero because a module name is not a symbol |
| Commented-out blocks | 18 candidates, 1% of files, median 4 lines |

The third one also plays to what this project can do that a linter cannot.
A linter can tell you code is unreachable. Only the history can tell you
whether it was commented out during an incident with a note saying to put
it back.

## What each candidate carries

Facts only, all of them read from git: the block's path and line range, its
size, and the commit blame attributes to those lines, oldest first when
there are several (sha, subject, body, author, date, days since). That
commit is usually the one that commented the block out, but blame answers
"who owns these lines now", so a formatter or a repo-wide sweep can own
them instead. The candidate carries the noise hints for that commit
alongside it, and reading the commit's diff is what settles it.
`look_first` is set when that commit's subject or body mentions an
incident, a revert, a rollback or a temporary disable. It is an ordering
hint, not a grade and not a filter.

Line numbers come from the file at HEAD and the blame runs against HEAD
too, so an uncommitted edit in the working tree changes no answer.

The body is the field that usually decides the answer. "Temporarily
disabled, restore after #3391" in a four-year-old commit tells you both
what this is and that nobody restored it.

Each candidate also carries an excerpt: up to `EXCERPT_LINES` lines of the
block's own text, each cut at `EXCERPT_MAX_CHARS` characters, comment
markers and leading asterisks stripped and nothing else, not normalized,
not summarized. It exists because the commit line can stop being useful
for telling candidates apart: measured against a real scan of an Elixir
repository, 43 candidates shared blame commits so heavily that 40 of them
traced to one 142-file merge, and the commit line alone could not tell
those 40 apart. Only the block's own text can.

That means the excerpt puts real code into the checklist, not a
description of it. Pasting that checklist into an issue moves that code
along with it. That is a path by which private code reaches a public
issue tracker, and whoever pastes the checklist should know it before
they do.

## Workflow

1. `python3 <skill>/scripts/scan.py --repo <repo> --path <dir>` and read the
   JSON.
2. `python3 <skill>/scripts/artifacts.py --scan scan.json --lang <lang>` for
   a checklist to paste into an issue.
3. Disclose the scan scope from `limits`, including what was skipped and
   whether the candidate cap was reached. The file counts in `limits` add
   up to what git tracks under the path: a cap that stops the scan early
   leaves the rest in `files_not_reached`, which is unexamined, not clean.
4. When the user picks one, run the ordinary single-target workflow on
   `path:start-end`: `trace.py`, a verdict, `verdict.py`, then `render.py`
   and `artifacts.py`. Every non-negotiable rule in `SKILL.md` applies to
   that verdict exactly as it would to any other.

## Boundaries, stated rather than worked around

- Block comments (`/* ... */`) are detected, for the extensions in
  `scanner.BLOCK_MARKERS`. A region opens only when the opening marker
  starts the (stripped) line: `/*` sitting mid-line, including inside a
  string literal, is not seen as an opener, since commented-out code
  almost always starts a line.
- A region opened with `/**` is a doc comment. It is discarded whole,
  never split into runs and never reported as a candidate.
- Nesting inside a block comment is not tracked: the first close marker
  found ends the region.
- The check that keeps a close marker from matching inside a string
  literal counts quote characters on that one physical line only. A
  string literal that itself spans several lines, a Kotlin text block, a
  C# verbatim string, a multi-line SQL or PHP literal, resets that count
  at every line break, so a `*/` that is really still inside the literal
  can end the region early.
- Code inside a comment that is documentation, a usage example, can be
  reported as a candidate. Reading its diff is what tells them apart.
- A language absent from `scanner.COMMENT_MARKERS` is not scanned, block
  comments included: `scan.py` decides whether to scan a file by its
  line-comment marker alone, and every extension in `scanner.BLOCK_MARKERS`
  already has one. The count of skipped files is in
  `limits.files_skipped_unsupported`.
- `look_first`'s vocabulary is English and Korean. Unlike the subject
  matching noise scoring deliberately refuses to do, this one filters
  nothing and decides nothing, so a missed word costs an ordering nudge,
  not a discarded candidate.

## What batch mode does not do

It does not grade, and it does not persist anything. The three artifacts
already persist a verdict where it will be read: a keep-comment lives in
the code, a pull request body lives in git history, and an unknown verdict
becomes a question to ask a person.
