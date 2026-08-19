"""Turn a `danger` keep-comment into a patch file the user applies.

This project never writes to the user's files: `gitq` allows sixteen
read-only git subcommands and there is no write path anywhere. This
module keeps that promise, which is the only reason it is allowed to
exist. It writes a unified diff to stdout, or to a path the user named
with `--out`, and nothing else. It does not open the target source file
for writing, and it does not run `git apply`. The user reads the diff and
applies it, or does not.

Two things follow from `git apply` patching the *working tree*:

- The context lines come from the file on disk, read with `open()`, not
  from `git show HEAD:<path>`. A patch built from HEAD is rejected the
  moment the file has one uncommitted edit. (Reading the working tree is
  a filesystem read, not a git query, so it does not go through `gitq`;
  this module makes no git calls at all.)
- The trace's own snippet was read from HEAD, so it is the record of what
  the investigation saw. When the file on disk no longer matches it at
  the recorded line numbers, the target has moved and the line numbers
  may now point at something else entirely. That is a refusal, not a
  best guess: a KEEP comment nailed above the wrong code is the same
  misattribution the rest of this project exists to prevent.

Every other doubt is a refusal too, for the same reason -- a wrong patch
is worse than no patch. See `Refused` for the full list of codes.

The refusal reasons are chrome this module writes, so they are looked up
in `_STRINGS` by `lang`, the same per-module pattern `artifacts.py` and
`render.py` use. Paths, line numbers and grades inside those sentences
are data, never translated. The comment text itself is not written here
at all: it comes from `artifacts.skeleton`, which already carries the
target file's own comment marker.
"""

import argparse
import json
import os
import sys

import artifacts
import scanner

# Lines of unchanged context on each side of the insertion point. Three
# is what `git diff` emits by default, so a patch from here reads like a
# patch from git.
CONTEXT_LINES = 3

# Every sentence this module writes, keyed by language then by a dotted
# key, exactly like `artifacts._STRINGS` and `render._STRINGS`. `en` is
# the default and the fallback target, so a partially translated future
# language degrades phrase by phrase instead of crashing.
#
# Each of these has to tell the reader what to do next, not just that
# something was wrong: a refusal a person cannot act on is a dead end.
_STRINGS = {
    "en": {
        "not-danger": "The verdict's grade is {grade}, not danger. A keep "
            "comment is the danger artifact; for {grade} run artifacts.py "
            "and use the artifact it produces.",
        "malformed-trace": "The trace is missing fields this needs "
            "(target.path, target.start, snippet.target_start, "
            "snippet.start_line, snippet.lines). Re-run the trace.",
        "malformed-verdict": "The verdict names no grade, so there is nothing "
            "here to act on. A keep comment is built only for a danger "
            "verdict; check the verdict against verdict.py's schema.",
        "no-snippet": "The trace recorded no usable snippet of the target "
            "({reason}), so there is nothing to check the file on disk "
            "against. Re-run the trace.",
        "no-marker": "No comment marker is known for {path}, and a patch has "
            "to produce code that still compiles, so none is guessed. Run "
            "artifacts.py and paste the keep comment above line {start} by "
            "hand, with the comment marker this file's language uses.",
        "outside-repo": "The trace's target path {path} does not resolve to a "
            "file inside {repo}, so no patch is built for it.",
        "missing-file": "{path} does not exist under {repo}. The file was "
            "moved or deleted after the trace; re-run the trace.",
        "binary-file": "{path} is not text, so no comment can be inserted "
            "into it.",
        "unreadable-file": "{path} could not be read: {error}.",
        "out-of-range": "{path} has {total} lines on disk, but the trace's "
            "target is lines {start}-{end}. The file changed after the "
            "trace; re-run the trace.",
        "target-moved": "Lines {start}-{end} of {path} on disk no longer "
            "match what the trace recorded there, so the file moved on "
            "since the investigation and those line numbers may point "
            "somewhere else now. Re-run the trace.",
        "not-a-comment": "The artifact for this verdict is not a plain keep "
            "comment (its citation resolves to no commit in this trace, or "
            "to no commit tagged as the introduction), so it cannot be "
            "inserted into source. Run artifacts.py to read what it says "
            "and act on that instead.",
    },
    "ko": {
        "not-danger": "검증(verdict)의 등급이 danger가 아니라 {grade}입니다. KEEP "
            "주석은 danger 등급의 결과물이므로, {grade} 등급이면 artifacts.py를 "
            "실행해 거기서 나온 결과물을 쓰세요.",
        "malformed-trace": "trace에 필요한 항목(target.path, target.start, "
            "snippet.target_start, snippet.start_line, snippet.lines)이 "
            "없습니다. trace를 다시 실행하세요.",
        "malformed-verdict": "검증(verdict)에 등급(grade)이 없어 판단할 근거가 "
            "없습니다. KEEP 주석은 danger 등급에만 만듭니다. verdict.py의 스키마와 "
            "맞는지 확인하세요.",
        "no-snippet": "trace가 대상의 발췌를 남기지 못했습니다({reason}). 디스크의 "
            "파일과 대조할 기준이 없으니 trace를 다시 실행하세요.",
        "no-marker": "{path}에 해당하는 주석 기호를 알 수 없습니다. 패치는 컴파일되는 "
            "코드를 만들어야 하므로 기호를 추측하지 않습니다. artifacts.py를 실행해 "
            "나온 KEEP 주석을 {start}번째 줄 위에 이 파일 언어의 주석 기호와 함께 "
            "직접 붙여넣으세요.",
        "outside-repo": "trace의 대상 경로 {path}가 {repo} 안의 파일로 해석되지 "
            "않습니다. 패치를 만들지 않습니다.",
        "missing-file": "{repo} 아래에 {path}가 없습니다. trace 이후 파일이 "
            "옮겨졌거나 삭제된 것이니 trace를 다시 실행하세요.",
        "binary-file": "{path}는 텍스트 파일이 아니므로 주석을 넣을 수 없습니다.",
        "unreadable-file": "{path}를 읽을 수 없습니다: {error}.",
        "out-of-range": "디스크의 {path}는 {total}줄인데 trace의 대상은 "
            "{start}-{end}줄입니다. trace 이후 파일이 바뀌었으니 trace를 다시 "
            "실행하세요.",
        "target-moved": "디스크의 {path} {start}-{end}줄이 trace가 기록한 내용과 "
            "다릅니다. 조사 시점 이후로 파일이 바뀌어 그 줄 번호가 다른 곳을 "
            "가리킬 수 있습니다. trace를 다시 실행하세요.",
        "not-a-comment": "이 검증(verdict)의 결과물은 순수한 KEEP 주석이 아닙니다"
            "(인용한 커밋이 이 trace에 없거나, 도입 커밋으로 표시된 것이 없습니다). "
            "소스에 넣을 수 없으니 artifacts.py를 실행해 내용을 읽고 그에 따라 "
            "처리하세요.",
    },
}


def _resolve_lang(lang):
    """An unknown lang value falls back to English rather than erroring,
    the same stance as `artifacts._resolve_lang`."""
    return lang if lang in _STRINGS else "en"


def _t(lang, key, **kwargs):
    """Look up `key` for `lang` (falling back to English), then format it."""
    lang = _resolve_lang(lang)
    template = _STRINGS[lang].get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


class Refused(Exception):
    """No patch was built, and why.

    `code` is stable and machine-readable; `str(exc)` is the sentence a
    person reads, and is translated. Callers that branch on a refusal
    branch on the code, never on the text.

    Codes:

    - not-danger: the grade is not `danger`.
    - malformed-verdict: the verdict names no grade at all.
    - malformed-trace: the trace lacks the target/snippet fields needed.
    - no-snippet: `snippet.available` is false.
    - no-marker: `scanner.marker_for` knows no marker for the extension.
    - outside-repo: the target path does not resolve inside the repo.
    - missing-file / binary-file / unreadable-file: the working tree file
      could not be read as text.
    - out-of-range: the target line numbers fall outside the file.
    - target-moved: the file on disk differs from what the trace recorded
      at those line numbers.
    - not-a-comment: the artifact for this verdict is not a comment block
      (an unresolved or non-introduction citation), so it cannot go into
      source code.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _refuse(lang, code, **kwargs):
    return Refused(code, _t(lang, code, **kwargs))


def _int_or_none(value):
    """`True` is an int to Python and a line number to nobody, so bools
    are rejected here rather than silently read as line 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _read_working_tree(repo, path, lang):
    """The target file's lines as they are on disk right now.

    Returns `(lines, ends_with_newline)`. `lines` is split on "\\n" only,
    not `str.splitlines()`, which also breaks on form feed and the
    Unicode line separators; git does not, and a line count that
    disagrees with git's would put the hunk header off by one. A line of
    a CRLF file keeps its trailing "\\r" so the context matches the file
    byte for byte.
    """
    root = os.path.realpath(repo)
    full = os.path.realpath(os.path.join(repo, path))
    if full != root and not full.startswith(root + os.sep):
        raise _refuse(lang, "outside-repo", path=path, repo=repo)

    try:
        with open(full, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise _refuse(lang, "missing-file", path=path, repo=repo)
    except OSError as exc:
        raise _refuse(lang, "unreadable-file", path=path, error=exc)

    if b"\x00" in raw:
        # git's own convention: a NUL byte means binary.
        raise _refuse(lang, "binary-file", path=path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(lang, "binary-file", path=path)

    lines = text.split("\n")
    ends_with_newline = len(lines) > 1 and lines[-1] == ""
    if ends_with_newline:
        lines.pop()
    return lines, ends_with_newline


def _recorded_target_lines(snippet, start, end, lang):
    """What the trace recorded on lines `start`..`end`.

    `snippet.lines` spans `snippet.start_line`..`snippet.end_line`, target
    lines and surrounding context together (see `trace._compute_snippet`),
    so the target's own lines are the slice at the offset of `start`
    within that span.
    """
    span_start = _int_or_none(snippet.get("start_line"))
    recorded = snippet.get("lines")
    if span_start is None or not isinstance(recorded, list):
        raise _refuse(lang, "malformed-trace")
    lo = start - span_start
    hi = end - span_start + 1
    if lo < 0 or hi > len(recorded):
        raise _refuse(lang, "malformed-trace")
    slice_ = recorded[lo:hi]
    if not slice_ or not all(isinstance(line, str) for line in slice_):
        raise _refuse(lang, "malformed-trace")
    return slice_


def _same_line(disk, recorded):
    """Whether a line on disk is the line the trace recorded.

    The trace's snippet came out of `str.splitlines()`, which drops the
    "\\r" of a CRLF file; the disk line keeps it (see
    `_read_working_tree`). Comparing them without normalising that would
    refuse every CRLF repository for a difference neither side actually
    has.
    """
    return disk.rstrip("\r") == recorded.rstrip("\r")


def _comment_lines(trace_data, verdict_data, marker, indent, lang):
    """The keep comment, indented to match the target line.

    The text comes from `artifacts.skeleton`, which already prefixes each
    line with the target file's own comment marker. It is checked, not
    trusted: an unresolved or non-introduction citation makes `skeleton`
    return a warning paragraph instead of a comment (see its `_top`), and
    that paragraph in a source file is a syntax error. Rather than
    reformat it into something insertable -- which would mean deciding
    what an unverified attribution should say, the exact guess this
    project refuses to make -- this refuses.
    """
    text = artifacts.skeleton("danger", trace_data,
                              verdict_data.get("evidence"), lang=lang)
    lines = text.split("\n")
    if not lines or not all(line.startswith(marker) for line in lines):
        raise _refuse(lang, "not-a-comment")
    return [indent + line for line in lines]


def _leading_whitespace(line):
    return line[:len(line) - len(line.lstrip())]


def _unified_diff(path, lines, ends_with_newline, insert_at, comment_lines):
    """A unified diff that inserts `comment_lines` above line `insert_at`.

    The hunk carries `CONTEXT_LINES` unchanged lines on each side, taken
    from `lines` (the working tree). A file whose last line has no
    trailing newline gets `\\ No newline at end of file` after that line
    when it falls inside the hunk; without it `git apply` rejects the
    patch for a content mismatch it cannot see.
    """
    total = len(lines)
    first = max(1, insert_at - CONTEXT_LINES)
    before = lines[first - 1:insert_at - 1]
    after = lines[insert_at - 1:insert_at - 1 + CONTEXT_LINES]

    body = [" " + line for line in before]
    body.extend("+" + line for line in comment_lines)
    body.extend(" " + line for line in after)
    if not ends_with_newline and insert_at - 1 + len(after) == total:
        body.append("\\ No newline at end of file")

    old_count = len(before) + len(after)
    new_count = old_count + len(comment_lines)
    header = "@@ -{},{} +{},{} @@".format(first, old_count, first, new_count)

    out = [
        "diff --git a/{0} b/{0}".format(path),
        "--- a/{}".format(path),
        "+++ b/{}".format(path),
        header,
    ]
    out.extend(body)
    return "\n".join(out) + "\n"


def build(trace_data, verdict_data, *, repo, lang="en"):
    """A unified diff inserting the keep comment above the target line.

    Raises `Refused` instead of guessing; see that class for the codes and
    this module's docstring for why every one of them is a refusal rather
    than a best effort. Never writes anything: the returned string is the
    whole output, and what the caller does with it is the caller's
    business.
    """
    if not isinstance(verdict_data, dict):
        raise _refuse(lang, "malformed-verdict")
    if not isinstance(trace_data, dict):
        raise _refuse(lang, "malformed-trace")

    # A grade that is not a string at all is a malformed verdict, not a
    # grade this tool declines to serve: naming it in the "grade is X, not
    # danger" sentence would put a dict or a None where a reader expects
    # one of verdict.py's four words.
    grade = verdict_data.get("grade")
    if not isinstance(grade, str) or not grade:
        raise _refuse(lang, "malformed-verdict")
    if grade != "danger":
        raise _refuse(lang, "not-danger", grade=grade)

    target = trace_data.get("target")
    snippet = trace_data.get("snippet")
    if not isinstance(target, dict) or not isinstance(snippet, dict):
        raise _refuse(lang, "malformed-trace")

    path = target.get("path")
    if not isinstance(path, str) or not path:
        raise _refuse(lang, "malformed-trace")

    if not snippet.get("available"):
        reason = snippet.get("reason")
        raise _refuse(lang, "no-snippet",
                      reason=reason if isinstance(reason, str) and reason
                      else "no reason recorded")

    # `snippet.target_start`/`target_end` are what the snippet's own line
    # numbering is anchored to, and `target_end` is already clamped to the
    # end of the file at trace time, so they are what the comparison below
    # must use. `target.start` has to agree with them; a hand-edited trace
    # where it does not is malformed, not a puzzle to solve.
    start = _int_or_none(snippet.get("target_start"))
    end = _int_or_none(snippet.get("target_end"))
    declared = _int_or_none(target.get("start"))
    if start is None or end is None or declared is None or declared != start:
        raise _refuse(lang, "malformed-trace")
    if end < start:
        raise _refuse(lang, "malformed-trace")

    # The marker check comes before the file is read: a file type with no
    # known comment marker is refused whatever its content, and saying so
    # is more useful than saying the file could not be read.
    marker = scanner.marker_for(path)
    if marker is None:
        raise _refuse(lang, "no-marker", path=path, start=start)

    lines, ends_with_newline = _read_working_tree(repo, path, lang)
    if start < 1 or end > len(lines):
        raise _refuse(lang, "out-of-range", path=path, total=len(lines),
                      start=start, end=end)

    recorded = _recorded_target_lines(snippet, start, end, lang)
    on_disk = lines[start - 1:end]
    if len(recorded) != len(on_disk) or not all(
            _same_line(d, r) for d, r in zip(on_disk, recorded)):
        raise _refuse(lang, "target-moved", path=path, start=start, end=end)

    indent = _leading_whitespace(lines[start - 1])
    comment_lines = _comment_lines(trace_data, verdict_data, marker, indent, lang)
    # A CRLF file's inserted lines end the way its existing lines do, so
    # the file keeps one line ending style rather than two.
    if lines[start - 1].endswith("\r"):
        comment_lines = [line + "\r" for line in comment_lines]

    return _unified_diff(path, lines, ends_with_newline, start, comment_lines)


def main():
    ap = argparse.ArgumentParser(
        description="Emit the danger keep-comment as a patch file. Prints a "
                    "unified diff; applying it is up to you (`git apply`). "
                    "Never writes to the target file.")
    ap.add_argument("--trace", required=True, help="a trace.py JSON file")
    ap.add_argument("--verdict", required=True, help="a verdict JSON file")
    ap.add_argument("--repo", default=None,
                    help="the repository to patch; defaults to the repo the "
                         "trace recorded. The patch's context lines are read "
                         "from this working tree, since that is what "
                         "`git apply` patches.")
    ap.add_argument("--out", default=None,
                    help="write the patch here instead of to stdout. Nothing "
                         "is written when the patch is refused.")
    ap.add_argument("--lang", default="en",
                    help="language for this tool's own wording and the keep "
                         "comment's (en, ko; unknown values fall back to en). "
                         "Paths, line numbers and shas are never translated.")
    args = ap.parse_args()

    with open(args.trace, encoding="utf-8") as fh:
        trace_data = json.load(fh)
    with open(args.verdict, encoding="utf-8") as fh:
        verdict_data = json.load(fh)

    repo = args.repo or trace_data.get("repo")
    if not isinstance(repo, str) or not repo:
        ap.error("--repo is required: the trace records no repo of its own")

    try:
        diff = build(trace_data, verdict_data, repo=repo, lang=args.lang)
    except Refused as exc:
        print("refused: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(diff)
        print("wrote {}. Review it, then apply it with: git apply {}".format(
            args.out, args.out), file=sys.stderr)
    else:
        sys.stdout.write(diff)


if __name__ == "__main__":
    main()
