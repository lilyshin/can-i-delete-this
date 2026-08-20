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
  non-zero and prints `INVALID: ...` on a schema violation, prints `valid`
  otherwise.
- `render.py`: `--trace`, `--verdict` (required); `--outdir` (defaults to
  the system temp directory); `--lang` (`en` or `ko`; an unknown value
  falls back to `en`).
- `artifacts.py`: either `--scan`, or both `--trace` and `--verdict`;
  `--copy` (writes to the clipboard when a clipboard tool is found);
  `--lang` (same values as `render.py`).
- `patch.py`: `--trace`, `--verdict` (required); `--repo` (defaults to the
  repo the trace recorded); `--out` (defaults to stdout); `--lang` (same
  values as `render.py`).

### The verdict schema (`verdict.py`)

- Grades: `danger`, `conditional`, `safe`, `unknown`.
- Evidence types: `commit`, `pr`, `issue`, `test`, `branch`.
- Evidence roles: `introduced`, `superseded`, `guard`, `reference`, `risk`.
  An evidence item may omit `role`; if present, it must be one of these.
- Artifact kinds, one per grade: `danger` to `keep-comment`, `conditional`
  to `checklist`, `safe` to `pr-body`, `unknown` to `question`.
- Any grade above `unknown` requires at least one evidence item of type
  `commit`. `conditional` additionally requires at least one condition.

### Trace-output keys a verdict needs to cite

To write a verdict, an agent cites entries out of `trace.py`'s output.
These keys, and what they hold, are stable:

- `introduction_candidates`: a list of candidates, each with `sha`,
  `subject`, `date`, and `why` (how the candidate was found, e.g.
  `"pickaxe"`, `"blame"`, `"cited"`).
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
  permanently. `trace.py` counts lines with `str.splitlines()`, which
  breaks on a form feed; `patch.py` counts lines by splitting on `"\n"`
  only, matching `git apply`. The two counts disagree on such a file, so
  the recorded line numbers cannot be trusted, and refusing is the safe
  side.
- The diff `patch.py` emits must be applied with `git apply` from the
  repository root. It is not applied for you.
- A KEEP comment's path lines can exceed a linter's maximum line length
  when the repository's own paths are long. The path is never shortened
  to fit, because a shortened path is no longer the fact it is reporting.
