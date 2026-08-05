"""Turn a verdict into something the user can paste somewhere useful.

The skill never writes to the user's files. It produces text and, when
asked, puts it on the clipboard.
"""

import argparse
import json
import posixpath
import shutil
import subprocess

CLIPBOARD_TOOLS = (
    ("pbcopy", ["pbcopy"]),
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
    ("clip", ["clip"]),
)

# Directory names that mark everything under them as test code.
_TEST_DIR_NAMES = {"tests", "test", "spec", "specs", "__tests__"}


def _top(trace_data):
    cands = trace_data.get("introduction_candidates") or []
    return cands[0] if cands else {}


def _is_test_path(path):
    """Identify test files by filename/directory convention, not substring match.

    Recognises:
      - any directory segment named tests/test/spec/specs/__tests__
      - filename stems starting with "test_" or ending with "_test"/"_spec"
      - a ".test." or ".spec." segment before the final extension
        (e.g. "foo.test.js", "foo.spec.ts")

    Deliberately does NOT match a bare "test"/"spec" substring anywhere in the
    path, which would misclassify files like "latest.py", "contest.py",
    "inspector.py", "specification.md" or "respect.go" as tests.
    """
    if not path:
        return False

    dirname, filename = posixpath.split(path)
    dir_parts = [p for p in dirname.split("/") if p]
    if any(part.lower() in _TEST_DIR_NAMES for part in dir_parts):
        return True

    segments = filename.lower().split(".")
    stem = segments[0]
    middle = segments[1:-1]  # segments between the stem and the final extension
    if "test" in middle or "spec" in middle:
        return True

    if stem.startswith("test_") or stem.endswith("_test") or stem.endswith("_spec"):
        return True

    return False


def _tests(trace_data):
    return [c["path"] for c in trace_data.get("co_changed", [])
            if _is_test_path(c["path"])]


def skeleton(grade, trace_data):
    """Return a fill-in-the-blank artifact for the agent to complete."""
    target = trace_data.get("target", {})
    top = _top(trace_data)
    sha = str(top.get("sha", ""))[:7] or "unknown"
    subject = top.get("subject", "")
    day = str(top.get("date", ""))[:10]
    tests = _tests(trace_data)
    guard = tests[0] if tests else None

    if grade == "danger":
        lines = ["// KEEP: {} ({}, {})".format(subject or "reason unknown", day, sha)]
        if guard:
            lines.append("// Before deleting, confirm {} still passes.".format(guard))
        else:
            lines.append("// WARNING: no test guards this. Add one before touching it.")
        return "\n".join(lines)

    if grade == "conditional":
        guard_line = "- [ ] Run {}".format(guard) if guard else "- [ ] Add a regression test first"
        return "\n".join([
            "Deletion checklist for {}:{}".format(target.get("path"), target.get("start")),
            "- [ ] Confirm the condition that made this necessary no longer holds",
            "- [ ] Introduced in {} ({})".format(sha, subject or "unknown"),
            guard_line,
            "- [ ] Get sign-off from someone who knows this area",
        ])

    if grade == "safe":
        guard_line = "- guarded by: {}".format(guard) if guard else "- no test depends on it"
        return "\n".join([
            "Remove dead guard in {}".format(target.get("path")),
            "",
            "This code was added in {} ({}).".format(sha, subject or "unknown"),
            "The reason it existed no longer applies, so it is safe to remove.",
            "",
            "Evidence:",
            "- introducing commit: {}".format(sha),
            guard_line,
        ])

    if grade == "unknown":
        who = top.get("author") or "unknown"
        mail = top.get("author_email") or "unknown"
        return "\n".join([
            "Question about {}:{}".format(target.get("path"), target.get("start")),
            "",
            "This looks intentional but I cannot find why it was added.",
            "Closest commit: {} ({}, {})".format(sha, subject or "no subject", day),
            "Author: {} <{}>".format(who, mail),
            "",
            "Does anyone remember whether this is still needed?",
        ])

    raise ValueError("unsupported grade: {!r}".format(grade))


def to_clipboard(text):
    """Copy text to the clipboard using the first available system tool.

    Returns the tool name on verified success, or "" if no tool is
    available, or if the tool ran but exited with a non-zero status
    (no display server, no pasteboard access, etc). A failed copy must
    not be reported as a success, so the exit code is checked rather
    than assumed.
    """
    for name, cmd in CLIPBOARD_TOOLS:
        if shutil.which(name):
            result = subprocess.run(cmd, input=text, text=True, check=False)
            return name if result.returncode == 0 else ""
    return ""


def main():
    ap = argparse.ArgumentParser(description="Emit the next-step artifact.")
    ap.add_argument("--trace", required=True)
    ap.add_argument("--verdict", required=True)
    ap.add_argument("--copy", action="store_true")
    args = ap.parse_args()
    with open(args.trace, encoding="utf-8") as fh:
        t = json.load(fh)
    with open(args.verdict, encoding="utf-8") as fh:
        v = json.load(fh)
    content = v.get("artifact", {}).get("content") or skeleton(v.get("grade", "unknown"), t)
    print(content)
    if args.copy:
        tool = to_clipboard(content)
        print("\n[copied with {}]".format(tool) if tool
              else "\n[no clipboard tool found; copy the text above]")


if __name__ == "__main__":
    main()
