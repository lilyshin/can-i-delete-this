"""Turn a verdict into something the user can paste somewhere useful.

The skill never writes to the user's files. It produces text and, when
asked, puts it on the clipboard.
"""

import argparse
import json
import posixpath
import shutil
import subprocess

import citation

CLIPBOARD_TOOLS = (
    ("pbcopy", ["pbcopy"]),
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
    ("clip", ["clip"]),
)

# Directory names that mark everything under them as test code.
_TEST_DIR_NAMES = {"tests", "test", "spec", "specs", "__tests__"}


def _top(trace_data, refs):
    """Pick the candidate the artifact should describe, and how it was found.

    Returns (candidate, status):

    - "cited": `candidate` is what the verdict's evidence cites, found by
      citation.find_cited in either introduction_candidates or
      blame_candidates. See citation.py for why the cited commit is not
      guaranteed to be in the first list: noise filtering can remove the
      real commit from introduction_candidates entirely (the N10 squash
      case is the common one), and SKILL.md's workflow then has the agent
      cite it out of blame_candidates anyway, after reading its diff.
    - "unresolved": the verdict cited a commit (`refs` is non-empty), but
      it names no commit in either list. verdict.py's schema only checks
      that a ref is a non-empty string, not that it names a real commit in
      this trace, so a stale or mistyped ref reaches here as a citation
      that resolves to nothing. `candidate` is {}. Substituting some other
      candidate here would be exactly the M2 misattribution this function
      exists to prevent, so callers must say the citation did not resolve,
      not guess a replacement.
    - "fallback": no citation was made at all (`refs` is empty).
      introduction_candidates is sorted chronologically, oldest first, and
      the oldest entry is used for lack of anything better, same as before
      this function knew about verdicts. `candidate` is {} if
      introduction_candidates is also empty (status is then "empty"
      instead, see below); this fallback only fires with a non-empty list.
    - "empty": no citation, and introduction_candidates is empty too.
      `candidate` is {}. This is the genuine "there is nothing to attribute
      to" case, where "reason unknown" text is honest rather than evasive.
    """
    cands = trace_data.get("introduction_candidates") or []
    if refs:
        found, _source = citation.find_cited(trace_data, refs)
        if found is not None:
            return found, "cited"
        return {}, "unresolved"
    if cands:
        return cands[0], "fallback"
    return {}, "empty"


def _unresolved_citation_text(grade, target, refs):
    """Artifact text for a citation that names no commit in this trace.

    Keeps the artifact useful even though the attribution is unresolved:
    the grade, the target, and the cited ref(s) are still worth carrying,
    and the reader needs to know the attribution has not been verified
    rather than be handed a confident guess (see _top's "unresolved"
    branch for why guessing is exactly the bug this avoids).
    """
    path = target.get("path", "unknown")
    start = target.get("start", "unknown")
    cited = ", ".join(refs) if refs else "unknown"
    return "\n".join([
        "Grade: {}".format(grade),
        "Target: {}:{}".format(path, start),
        "",
        "The verdict cites commit {} as evidence, but no commit with that "
        "prefix was found in this trace (checked introduction_candidates "
        "and blame_candidates).".format(cited),
        "This attribution could not be verified. Do not treat this grade "
        "as confirmed; re-run the trace or check the citation by hand "
        "before acting on it.",
    ])


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


def _tests(trace_data, real_sha=None):
    """Co-changed test paths, restricted to the commit the artifact is about.

    trace.py now records co_changed across every introduction candidate, not
    just one, because it cannot itself tell which one is real (see _top).
    Without this filter a test added alongside a different, uncited
    candidate could be misreported as guarding the commit this artifact
    names. When `real_sha` is None (no candidate was resolved at all),
    nothing is attributed to anything, so no entries match.
    """
    return [c["path"] for c in trace_data.get("co_changed", [])
            if _is_test_path(c["path"]) and real_sha is not None
            and c.get("sha") == real_sha]


def skeleton(grade, trace_data, evidence=None):
    """Return a fill-in-the-blank artifact for the agent to complete.

    `evidence` is the verdict's own `evidence` list (commit/pr/issue/test
    entries). Passing it lets `_top` prefer the candidate the verdict
    actually cites over the chronologically-oldest one; see `_top`'s
    docstring. It is optional and defaults to None so existing callers that
    have not been updated keep the previous (oldest-candidate) behavior.
    """
    target = trace_data.get("target", {})
    refs = citation.commit_refs(evidence)
    top, status = _top(trace_data, refs)

    if status == "unresolved":
        return _unresolved_citation_text(grade, target, refs)

    # Every field below is checked with isinstance() before use, not coerced
    # with str(). str(x) turns a missing/None date into "" or "None" and lets
    # it leak straight into the rendered text (e.g. "// KEEP: hotfix (None,
    # a3f8c21)"); isinstance() plus an explicit fallback keeps that from
    # happening when introduction_candidates is empty, as it is for F4-style
    # squash cases (see tests/test_trace_cases.py::test_reports_why_it_came_up_empty).
    raw_sha = top.get("sha")
    sha = raw_sha[:7] if isinstance(raw_sha, str) and raw_sha else "unknown"

    raw_subject = top.get("subject")
    subject = raw_subject if isinstance(raw_subject, str) and raw_subject else ""

    raw_date = top.get("date")
    day = raw_date[:10] if isinstance(raw_date, str) and raw_date else "date unknown"

    tests = _tests(trace_data, raw_sha if isinstance(raw_sha, str) and raw_sha else None)
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
        raw_author = top.get("author")
        who = raw_author if isinstance(raw_author, str) and raw_author else "unknown"
        raw_mail = top.get("author_email")
        mail = raw_mail if isinstance(raw_mail, str) and raw_mail else "unknown"

        lines = [
            "Question about {}:{}".format(target.get("path"), target.get("start")),
            "",
            "This looks intentional but I cannot find why it was added.",
            "Closest commit: {} ({}, {})".format(sha, subject or "no subject", day),
            "Author: {} <{}>".format(who, mail),
        ]

        # unknown means the investigation found nothing conclusive; notes is
        # the only place that records how far it got and where it stopped
        # (e.g. "blame returned only noise commits; falling back to
        # pickaxe"), so surface it instead of dropping it on the floor.
        raw_notes = trace_data.get("notes")
        note_lines = [n for n in (raw_notes or []) if isinstance(n, str) and n.strip()] \
            if isinstance(raw_notes, list) else []
        if note_lines:
            lines.append("")
            lines.append("Investigation notes:")
            lines.extend("- {}".format(n) for n in note_lines)

        limits = trace_data.get("limits")
        if isinstance(limits, dict):
            scope_flags = []
            if limits.get("truncated"):
                scope_flags.append("history search was truncated")
            if limits.get("candidate_cap_reached"):
                scope_flags.append("candidate cap was reached")
            if scope_flags:
                lines.append("")
                lines.append("Search was limited: {}.".format("; ".join(scope_flags)))

        lines.append("")
        lines.append("Does anyone remember whether this is still needed?")
        return "\n".join(lines)

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
    content = v.get("artifact", {}).get("content") or skeleton(
        v.get("grade", "unknown"), t, v.get("evidence"))
    print(content)
    if args.copy:
        tool = to_clipboard(content)
        print("\n[copied with {}]".format(tool) if tool
              else "\n[no clipboard tool found; copy the text above]")


if __name__ == "__main__":
    main()
