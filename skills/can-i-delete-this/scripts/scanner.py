"""Find blocks of commented-out code.

Pure functions only. This module never touches git, and imports nothing
from this project.

A block is a run of consecutive line comments whose text looks like code
rather than prose. That signal was chosen by measurement over two
alternatives (see docs/specs, not shipped): against a 1710-file Kotlin
repository it found 18 blocks, 1% of files, where an unreferenced-file
signal was estimated at 240 candidates, extrapolated from a 150-file
sample that produced 21, of which roughly one in ten was plausible.

What decides a block is deliberately narrow, because the cost of a false
positive is a reader's time and the cost of a false negative is a block
nobody looks at again:

- A line matching `_NOT_CODE` (a TODO, an annotation, a license header, a
  URL) ends the current run rather than being dropped from it. A TODO in
  the middle of commented-out code separates two blocks; it does not join
  them.
- Blank comment lines stay inside a block's span but are left out of the
  code-shape ratio. A commented-out function usually has blank lines in
  it, and counting them as prose would reject the block.
- `looks_like_code` is not a parser. It asks whether the text carries
  syntax a sentence would not.

Block comments (`/* ... */`) are found too, when `find_blocks` is given a
`block` marker pair. A doc comment (a region opened with `/**`) is always
discarded whole: measured against a 1710-file Kotlin repository, 3 `/* */`
regions were code-shaped candidates and 6 `/** */` doc comments were also
code-shaped text; without the `/**` exclusion this feature would have
produced twice as many false candidates as real ones.

Declared boundaries of the block-comment scan, so a reader does not have
to rediscover them:

- Nesting is not tracked. The first close marker found ends the region,
  the same no-parser stance as everywhere else in this module.
- A candidate close marker preceded on its line by an odd number of
  double quotes (`"`) is assumed to sit inside a string literal and is
  skipped for the next one. This is a heuristic, not a parser: an escaped
  quote inside a string will fool it, and a single-quoted string holding
  the close marker is not protected at all. Only `"` is counted because
  an apostrophe in ordinary prose is far more common than `'*/'` in code:
  counting `'` too made a prose closing line fail to close, and the
  region then ran on and swallowed the live code after it.
- Text outside the markers on the opening and closing lines, including
  any code that follows a close marker on its own line, is not part of
  the body and is not re-examined as code or as a new comment.
- The reported span reaches back to the opening line and forward to the
  closing line only when the region closes without an interior run being
  cut short by `_NOT_CODE` first. A `_NOT_CODE` line that ends a run
  before the true closer is reached reports only that run's own content
  lines; the region's marker lines are not retroactively attached to it.
- When the closing line carries body text before its close marker, that
  line is part of the run, so the reported span reaches a line that holds
  the close marker and anything after it. Deleting the span as printed
  therefore takes that closing line too, which is right for a whole
  region and worth a look when code follows the marker on it.
- `/**` opens a doc comment and is discarded whole, but the line-comment
  doc styles `///` and `//!` are not: they start with the line-comment
  marker, so `/// let x = foo();` reaches the line-comment path and can
  become a candidate. The asymmetry is deliberate for now; the `/**`
  exclusion was measured and these were not.
"""

import re
from dataclasses import dataclass

# One line-comment marker per file extension. A language absent from this
# table is not scanned at all, and `scan.py` counts what it skipped rather
# than guessing a marker.
COMMENT_MARKERS = {
    "kt": "//", "kts": "//", "java": "//", "swift": "//", "scala": "//",
    "js": "//", "jsx": "//", "ts": "//", "tsx": "//", "go": "//",
    "c": "//", "h": "//", "cc": "//", "cpp": "//", "hpp": "//",
    "cs": "//", "rs": "//", "dart": "//", "php": "//",
    "py": "#", "rb": "#", "ex": "#", "exs": "#", "sh": "#", "bash": "#",
    "zsh": "#", "pl": "#", "r": "#", "yml": "#", "yaml": "#", "tf": "#",
    "lua": "--", "sql": "--", "hs": "--", "elm": "--",
}

# One block-comment marker pair per file extension, for languages that
# have `/* ... */` on top of (or instead of) a line-comment marker. An
# extension absent from this table has no block-comment scanning at all.
BLOCK_MARKERS = {
    ext: ("/*", "*/")
    for ext in ("kt kts java js jsx ts tsx go c h cc cpp hpp cs rs scala "
                "swift dart php sql").split()
}

# A comment run shorter than this is not a candidate. Two commented lines
# are as often a note as they are dead code.
MIN_BLOCK_LINES = 3

# Of the run's non-blank comment lines, at least this fraction must look
# like code.
CODE_SHAPE_RATIO = 0.7

# How much of a block's own text rides along with it. Measured against a
# real scan of an Elixir repository: 43 candidates shared blame commits so
# heavily that 40 of them traced to one 142-file merge; the commit line
# alone could not tell those 40 apart; only the block's own text can.
EXCERPT_LINES = 2
EXCERPT_MAX_CHARS = 120

_CODE_SHAPE = (
    re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*\("),
    re.compile(r"[=;{}]"),
    re.compile(r"^\s*(val|var|let|const|if|for|while|return|import|from|fun"
               r"|def|defp|defmodule|case|class|new|await|async|public"
               r"|private|select|update|delete|insert)\b"),
)

# Text that is a note, a directive, a license or a link, none of which is
# code someone forgot to delete.
_NOT_CODE = re.compile(
    r"^\s*(TODO|FIXME|NOTE|XXX|HACK|WARNING|WARN|@|noinspection|ktlint"
    r"|suppress|Copyright|SPDX|Licen[cs]e|https?:|www\.)", re.I)


@dataclass(frozen=True)
class Block:
    """A run of commented-out code. `start` and `end` are 1-based line
    numbers and `end` is inclusive, matching the `path:start-end` shape the
    rest of this project uses.

    `lines` is the span, blank comment lines included. `code_lines` is how
    many of them looked like code, which is what the ratio was judged on.
    `excerpt` is up to `EXCERPT_LINES` of the block's own non-blank text,
    each cut at `EXCERPT_MAX_CHARS`, comment marker, a leading asterisk and
    indentation stripped and nothing else: not normalized, not summarized.
    `excerpt_truncated` says whether that cut actually removed anything, so
    a reader is told the excerpt is short of the line rather than left to
    assume it is the whole line.
    """
    start: int
    end: int
    lines: int
    code_lines: int
    excerpt: tuple = ()
    excerpt_truncated: bool = False


def marker_for(path):
    """The line-comment marker for `path`, or None when the extension is
    not in `COMMENT_MARKERS`."""
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return COMMENT_MARKERS.get(name.rsplit(".", 1)[-1].lower())


def block_markers_for(path):
    """The `(open, close)` block-comment marker pair for `path`, or None
    when the extension is not in `BLOCK_MARKERS`."""
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return BLOCK_MARKERS.get(name.rsplit(".", 1)[-1].lower())


def looks_like_code(text):
    """True when `text` carries syntax prose would not."""
    return any(pattern.search(text) for pattern in _CODE_SHAPE)


def _strip_block_prefix(text):
    """The body of one line inside a `/* ... */` region: a leading `*`,
    the usual continuation style for these comments, is removed. Anything
    else is left exactly as it appears in the file."""
    return text[1:] if text.startswith("*") else text


def _closer_index(text, close_marker):
    """Position of the first `close_marker` in `text` that is not sitting
    inside a string literal, or -1 if there is none. A candidate is
    treated as being inside a string when the text before it holds an odd
    number of double quotes (`"`); that candidate is skipped and the
    search continues for the next one.

    Single quotes are not counted, so a `'*/'` literal is not protected.
    Counting them cost far more than it bought: an apostrophe in a prose
    closing line (`/* ... unless there's an error */`) made the count odd,
    the real closer was skipped, and the region ran on over the live code
    below it. Measured over 55,575 C-family files in 139 local
    repositories, counting `'` skipped 169 real closers and invented 41
    candidates covering 1,398 lines that the double-quote-only count does
    not report, while losing nothing: every one of those 41 spans overlaps
    no span the double-quote-only count finds.
    """
    start = 0
    while True:
        idx = text.find(close_marker, start)
        if idx == -1:
            return -1
        if text.count('"', 0, idx) % 2 == 0:
            return idx
        start = idx + len(close_marker)


def _emit(run, blocks, min_lines, ratio):
    """Turn one finished comment run into a Block, or drop it."""
    if len(run) < min_lines:
        return
    content = [text for _, text in run if text.strip()]
    code = [text for text in content if looks_like_code(text)]
    if len(code) < min_lines:
        return
    if len(code) < len(content) * ratio:
        return
    shown = [text.strip() for text in content[:EXCERPT_LINES]]
    excerpt = tuple(text[:EXCERPT_MAX_CHARS] for text in shown)
    truncated = any(len(text) > EXCERPT_MAX_CHARS for text in shown)
    blocks.append(Block(start=run[0][0], end=run[-1][0], lines=len(run),
                        code_lines=len(code), excerpt=excerpt,
                        excerpt_truncated=truncated))


def find_blocks(text, marker, *, block=None, min_lines=MIN_BLOCK_LINES,
                ratio=CODE_SHAPE_RATIO):
    """Every run of commented-out code in `text`, in line order.

    `marker` finds runs of line comments, as before. `block`, given as an
    `(open, close)` pair such as `("/*", "*/")`, additionally finds runs
    inside block comments; whatever either scan finds is merged and
    returned in line order. `block=None`, the default, keeps the old
    line-comments-only behaviour.

    A block-comment region opens only when a stripped line starts with
    the open marker: `/*` elsewhere on a line, including inside a string
    literal, is ignored, since commented-out code almost always starts a
    line. A region opened with `/**` is a doc comment; it is discarded
    whole rather than split into runs. Nesting is not tracked: the first
    close marker found ends the region, matching this module's no-parser
    stance everywhere else. Text outside the markers on the opening and
    closing lines, including any code that follows a close marker on its
    own line, is not part of the body and is not re-examined.
    """
    open_marker, close_marker = block if block is not None else (None, None)

    blocks = []
    line_run = []
    block_run = []
    in_block = False
    block_is_doc = False
    region_open_line = None
    region_first_run = True
    opener_has_content = False

    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()

        if in_block:
            close_idx = _closer_index(stripped, close_marker)
            if close_idx != -1:
                before = _strip_block_prefix(stripped[:close_idx])
                closed_here = bool(before.strip())
                if closed_here:
                    block_run.append((lineno, before))
                if not block_is_doc:
                    # The region's own marker lines belong to a run only
                    # when that run is the whole region: then the span is
                    # the range a reader would delete. A run an interior
                    # `_NOT_CODE` line already cut short is not, and
                    # attaching the closer to it would print a span whose
                    # deletion leaves the region unterminated.
                    if region_first_run:
                        if not opener_has_content:
                            block_run.insert(0, (region_open_line, ""))
                        if not closed_here:
                            block_run.append((lineno, ""))
                    _emit(block_run, blocks, min_lines, ratio)
                in_block = False
                block_run = []
                region_first_run = True
                opener_has_content = False
                continue
            if block_is_doc:
                continue
            body = _strip_block_prefix(stripped)
            if _NOT_CODE.match(body):
                _emit(block_run, blocks, min_lines, ratio)
                block_run = []
                region_first_run = False
                continue
            block_run.append((lineno, body))
            continue

        if marker and stripped.startswith(marker):
            body = stripped[len(marker):]
            if _NOT_CODE.match(body):
                _emit(line_run, blocks, min_lines, ratio)
                line_run = []
                continue
            line_run.append((lineno, body))
            continue

        if open_marker and stripped.startswith(open_marker):
            _emit(line_run, blocks, min_lines, ratio)
            line_run = []
            after_open = stripped[len(open_marker):]
            is_doc = after_open.startswith("*")
            close_idx = _closer_index(after_open, close_marker)
            if close_idx != -1:
                # Opens and closes on the same line: one line of body,
                # handed to _emit like any other run. At the default
                # min_lines it is dropped for being short; at
                # `min_lines=1`, which the caller may ask for, it is
                # reported, because one commented-out line of code is
                # what the caller asked to see.
                if not is_doc:
                    body = _strip_block_prefix(after_open[:close_idx].lstrip())
                    _emit([(lineno, body)], blocks, min_lines, ratio)
                continue
            in_block = True
            block_is_doc = is_doc
            region_open_line = lineno
            region_first_run = True
            opener_has_content = bool(after_open.strip())
            if opener_has_content and not is_doc:
                opener_body = _strip_block_prefix(after_open.lstrip())
                block_run = [(lineno, opener_body)]
            else:
                block_run = []
            continue

        _emit(line_run, blocks, min_lines, ratio)
        line_run = []

    _emit(line_run, blocks, min_lines, ratio)
    if in_block and not block_is_doc:
        if region_first_run and not opener_has_content:
            block_run.insert(0, (region_open_line, ""))
        _emit(block_run, blocks, min_lines, ratio)

    blocks.sort(key=lambda found: found.start)
    return blocks
