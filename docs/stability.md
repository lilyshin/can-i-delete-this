# Stability

This project versions from 1.0.0 under semantic versioning. This page says
what that promise covers and what it does not, so a script that reads
`trace.py`'s JSON directly knows what it can depend on.

## What is stable

### Skill entry points

`/can-i-delete-this:check` and `/can-i-delete-this:scan` keep their names
and their argument shape: a target (`path:line`, `path:start-end`, a bare
symbol, or nothing) for `check`, a directory or file for `scan`.

### CLI flags

Each script's flag names and what they mean do not change. Defaults tuned
for noise scoring or search limits can still move between releases; the
flag itself, and what passing it does, does not.

- `trace.py`: `--repo`, `--file`, `--lines` (required); `--max-commits`,
  `--since`, `--max-candidates`, `--max-co-changed` (override the search
  and result limits); `--include-commit` (repeatable, adds a commit to
  `introduction_candidates` with `why: "cited"` after verifying it exists
  in the repository).
- `scan.py`: `--repo` (required); `--path` (defaults to the repo root);
  `--min-lines`, `--max-candidates`.
- `verdict.py`: a single positional path to a verdict JSON file; exits
  non-zero and prints `INVALID: ...` to stderr on a schema violation,
  prints `valid` to stdout otherwise.
- `render.py`: `--trace`, `--verdict` (required); `--outdir` (defaults to
  the system temp directory); `--lang` (`en` or `ko`; an unknown value
  falls back to `en`). Prints the path of the report it wrote to stdout;
  that print is the only way a caller learns where the report went.
- `artifacts.py`: either `--scan`, or both `--trace` and `--verdict`;
  `--copy` (writes to the clipboard when a clipboard tool is found);
  `--lang` (same values as `render.py`).
- `patch.py`: `--trace`, `--verdict` (required); `--repo` (defaults to the
  repo the trace recorded); `--out` (defaults to stdout); `--lang` (same
  values as `render.py`).

### Exit codes

Every script uses `0` for success and `2` for a usage error (a missing or
malformed command-line argument; argparse's own convention). Beyond that,
each script's own failure mode gets `1`:

- `trace.py`: `1` when the underlying git command fails (a path git
  cannot find, a line range past the end of the file, and similar).
- `scan.py`: `1` on the same class of git failure.
- `verdict.py`: `1` when the verdict fails schema validation.
- `patch.py`: `1` when the patch is refused. `Refused.code` (see that
  class in `patch.py`) is itself stable and machine-readable, the one
  promise this page makes about an exception's own attribute rather than
  a process exit code; a caller branches on `code`, never on the
  refusal's translated text.
- `render.py` and `artifacts.py` make no git calls of their own and have
  no refusal path, so `1` from either is an unhandled exception (a
  missing input file, JSON that will not parse), not a code either
  script chooses on purpose.

### The verdict schema (`verdict.py`)

- Grades: `danger`, `conditional`, `safe`, `unknown`.
- Evidence types: `commit`, `pr`, `issue`, `test`, `branch`.
- Evidence roles: `introduced`, `superseded`, `guard`, `reference`, `risk`.
  An evidence item may omit `role`; if present, it must be one of these.
- Artifact kinds, one per grade: `danger` to `keep-comment`, `conditional`
  to `checklist`, `safe` to `pr-body`, `unknown` to `question`.
- `summary` must be a non-empty string, for every grade.
- `artifact` must be an object whose `kind` matches the grade (one of the
  kinds above); `artifact.content` must be a non-empty string.
- Any grade above `unknown` requires at least one evidence item of type
  `commit`. `conditional` additionally requires at least one condition.

### Trace-output keys a verdict needs to cite

To write a verdict, an agent cites entries out of `trace.py`'s output.
These keys, and what they hold, are stable:

- `introduction_candidates`: a list of candidates, each with `sha`,
  `subject`, `date`, and `why` (how the candidate was found: `"blame"`,
  `"pickaxe"`, `"line-history"`, or `"cited"` for a commit added through
  `--include-commit`).
- `blame_candidates`: a list of candidates sourced from `git blame`
  instead of pickaxe and line history, each with `sha`, `subject`, and
  `date`. Unlike `introduction_candidates`, there is no `why` here, since
  every entry is a blame hit by construction. Each entry also carries a
  noise assessment; its keys and values follow the noise-scoring rules,
  which are not stable (see "What is not stable" below).
- `target`: the path and line range under investigation.

## What is not stable

- Every other key in `trace.py`'s output, and the shape of its values.
  `co_changed` is the example: 0.9.2 added a per-commit cap to it and a
  `co_changed_totals` sibling recording the true count. Neither existed
  before that release, and either could change shape again without a
  major version bump, because a verdict is never required to cite them.
- Noise-scoring signals and thresholds (what counts as a formatter sweep,
  a vendored dump, and so on, and where the cutoffs sit).
- The HTML report's structure (`render.py`'s markup, styling, layout).
- Human-facing wording, in either language: report text, artifact text,
  error and refusal messages.

## `skeleton()`'s contract

`artifacts.py`'s `skeleton()` is an internal function, not a CLI surface,
but it is called directly by tests and by anyone importing the module, so
its contract is worth stating precisely. The supported call passes
`evidence` (a verdict's own `evidence` list). Called that way:

- If `evidence` cites a commit under role `introduced` or no role at all,
  and that commit resolves to a real candidate, the artifact names it.
- If the citation does not resolve, or cites only non-introducing roles
  (`superseded`, `reference`, `guard`, `risk`), the artifact says so
  instead of guessing a candidate.

Called without `evidence` (the unsupported path, kept only so old callers
do not break): if `introduction_candidates` has exactly one entry, or the
grade is `unknown`, `skeleton()` cites that one candidate, same as before
`evidence` existed. If there is more than one candidate and the grade is
not `unknown`, it returns text that states the candidate count and cites
none of them; `patch.py` refuses to build a patch from that text, since it
names no commit to attach the patch to.

## Known limitations

- A file containing a form feed character is refused by `patch.py`
  permanently. `str.splitlines()` (used to number the target's own
  snippet) treats a form feed as a line break; `patch.py` counts lines by
  splitting on `"\n"` only, matching `git apply`. The two would disagree
  on such a file, so `trace.py` detects the form feed itself and records
  the target's snippet as unavailable, which makes `patch.py` refuse
  through its `no-snippet` check unconditionally, rather than only when
  the resulting line-number disagreement happens to fall inside the
  snippet's own recorded window.
- The diff `patch.py` emits must be applied with `git apply` from the
  repository root. It is not applied for you.
- A KEEP comment can exceed a linter's maximum line length, on either of
  the two lines that carry a fact rather than this project's wording: the
  path line, when the repository's own paths are long, and the `KEEP:`
  line, which carries the introducing commit's subject. Neither is ever
  shortened to fit, because a shortened path or a truncated subject is no
  longer the fact it is reporting. Every other line is this project's own
  wording, and that wording is kept to 75 characters or fewer (leaving
  room for a 4-space indent under a linter's typical 79-column default),
  so the wording never causes the overage on its own.
