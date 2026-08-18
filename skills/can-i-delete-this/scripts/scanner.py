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

Known boundary, disclosed rather than worked around: block comments
(`/* ... */`) are not detected. Only line comments.
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

# A comment run shorter than this is not a candidate. Two commented lines
# are as often a note as they are dead code.
MIN_BLOCK_LINES = 3

# Of the run's non-blank comment lines, at least this fraction must look
# like code.
CODE_SHAPE_RATIO = 0.7

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
    """
    start: int
    end: int
    lines: int
    code_lines: int


def marker_for(path):
    """The line-comment marker for `path`, or None when the extension is
    not in `COMMENT_MARKERS`."""
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return COMMENT_MARKERS.get(name.rsplit(".", 1)[-1].lower())


def looks_like_code(text):
    """True when `text` carries syntax prose would not."""
    return any(pattern.search(text) for pattern in _CODE_SHAPE)


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
    blocks.append(Block(start=run[0][0], end=run[-1][0], lines=len(run),
                        code_lines=len(code)))


def find_blocks(text, marker, *, min_lines=MIN_BLOCK_LINES,
                ratio=CODE_SHAPE_RATIO):
    """Every run of commented-out code in `text`, in line order."""
    blocks = []
    run = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(marker):
            body = stripped[len(marker):]
            if _NOT_CODE.match(body):
                _emit(run, blocks, min_lines, ratio)
                run = []
                continue
            run.append((lineno, body))
            continue
        _emit(run, blocks, min_lines, ratio)
        run = []
    _emit(run, blocks, min_lines, ratio)
    return blocks
