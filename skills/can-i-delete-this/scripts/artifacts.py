"""Turn a verdict into something the user can paste somewhere useful.

The skill never writes to the user's files. It produces text and, when
asked, puts it on the clipboard.

Every piece of chrome this module writes around the trace/verdict data
(the "// KEEP:", the checklist wording, the "Grade:"/"Target:" labels, the
unresolved-citation message, and the placeholder words used when a field
is missing) is looked up in `_STRINGS` by `lang`; see that dict's
docstring. SHAs, paths, commit subjects, author names and dates are always
data read from the trace or the verdict, never translated.
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

# Every piece of text this module writes around the data it renders, keyed
# by language then by a dotted string key. This is a plain data lookup, not
# gettext: adding a third language means adding a third top-level key with
# every key of `en` translated, not touching any function below. `en` is
# the default and the fallback target (see `_resolve_lang`), so its text
# must stay exactly what shipped before this table existed -- the existing
# test suite calls `skeleton()` with no `lang` argument and pins the exact
# text that produces.
#
# `common.*` holds the placeholder words substituted when a field trace.py
# could not resolve is missing (a missing sha, subject, date, author or
# email); those words are written by this module, not read from git, so
# they are chrome like everything else here, not data.
_STRINGS = {
    "en": {
        "label.grade": "Grade",
        "label.target": "Target",
        "unresolved.cited": "The verdict cites commit {cited} as evidence, but no "
            "commit with that prefix was found in this trace (checked "
            "introduction_candidates and blame_candidates).",
        "unresolved.warning": "This attribution could not be verified. Do not treat "
            "this grade as confirmed; re-run the trace or check the citation by "
            "hand before acting on it.",
        "not_introduction.cited": "The verdict's evidence cites {cited}, but none of "
            "it is tagged as the real introduction (role: introduced, or no role at "
            "all). This trace has nothing to attribute this artifact to.",

        "danger.keep": "// KEEP: {subject} ({day}, {sha})",
        "danger.guard": "// Before deleting, confirm {guard} still passes.",
        "danger.warning": "// WARNING: no test guards this. Add one before touching it.",

        "conditional.title": "Deletion checklist for {path}:{start}",
        "conditional.condition": "- [ ] Confirm the condition that made this "
            "necessary no longer holds",
        "conditional.introduced": "- [ ] Introduced in {sha} ({subject})",
        "conditional.run_guard": "- [ ] Run {guard}",
        "conditional.add_test": "- [ ] Add a regression test first",
        "conditional.signoff": "- [ ] Get sign-off from someone who knows this area",

        "safe.title": "Remove dead guard in {path}",
        "safe.added": "This code was added in {sha} ({subject}).",
        "safe.rationale": "The reason it existed no longer applies, so it is "
            "safe to remove.",
        "safe.evidence_header": "Evidence:",
        "safe.introducing_commit": "- introducing commit: {sha}",
        "safe.guarded_by": "- guarded by: {guard}",
        "safe.no_test": "- no test depends on it",

        "unknown.title": "Question about {path}:{start}",
        "unknown.body": "This looks intentional but I cannot find why it was added.",
        "unknown.closest": "Closest commit: {sha} ({subject}, {day})",
        "unknown.author": "Author: {who} <{mail}>",
        "unknown.notes_header": "Investigation notes:",
        "unknown.limited": "Search was limited: {scope}.",
        "unknown.scope_truncated": "history search was truncated",
        "unknown.scope_cap": "candidate cap was reached",
        "unknown.closing": "Does anyone remember whether this is still needed?",

        "common.unknown": "unknown",
        "common.reason_unknown": "reason unknown",
        "common.no_subject": "no subject",
        "common.date_unknown": "date unknown",

        "scan.header": "Commented-out code candidates: {count} ({path})",
        "scan.none": "No commented-out code blocks found under {path}.",
        "scan.none_capped": "No candidates are listed for {path}: the scan "
                             "stopped at the candidate cap before reporting "
                             "any, so nothing here says the blocks are absent.",
        "scan.intro": "Oldest first. Nothing here is graded. To grade one, run "
                       "`/can-i-delete-this:check <path>:<start>-<end>`.",
        "scan.look_first": "look first",
        "scan.item_meta": "{lines} lines, commented out {age} days ago",
        "scan.item_meta_unknown": "{lines} lines, commenting commit unknown",
        "scan.body_truncated": "(body truncated; `git show {sha}` for the rest)",
        "scan.touched_by": "{count} commits touched these lines; the oldest is shown",
        "scan.hints": "about that commit: {hints}",
        "scan.scope": "Scan scope: {scanned} of {total} files "
                       "({unsupported} skipped as unsupported, {vendored} vendored, "
                       "{generated} generated, {too_large} too large to read, "
                       "{missing_at_head} missing at HEAD, {not_reached} never "
                       "examined after the candidate cap).",
        "scan.cap": "Candidate cap of {cap} was reached; more may exist.",
        "scan.boundary": "Block comments (`/* ... */`) are not detected.",
    },
    "ko": {
        "label.grade": "등급",
        "label.target": "대상",
        "unresolved.cited": "검증(verdict)이 커밋 {cited}을 근거로 인용했지만, 이 "
            "trace의 introduction_candidates와 blame_candidates 어디에도 해당 "
            "prefix를 가진 커밋이 없습니다.",
        "unresolved.warning": "이 귀속(attribution)은 검증되지 않았습니다. 이 등급을 "
            "확정된 것으로 보지 말고, trace를 다시 돌리거나 인용을 직접 확인한 뒤 "
            "판단하세요.",
        "not_introduction.cited": "검증(verdict)의 근거가 {cited}을 인용했지만, 그중 "
            "어느 것도 실제 도입(role: introduced 또는 role 없음)으로 표시되어 있지 "
            "않습니다. 이 trace에는 이 결과물의 근거로 삼을 대상이 없습니다.",

        "danger.keep": "// 유지: {subject} ({day}, {sha})",
        "danger.guard": "// 삭제하기 전에 {guard}가 통과하는지 확인하세요.",
        "danger.warning": "// 주의: 이 코드를 지켜주는 테스트가 없습니다. 손대기 전에 "
            "테스트를 추가하세요.",

        "conditional.title": "{path}:{start} 삭제 체크리스트:",
        "conditional.condition": "- [ ] 이 코드가 필요했던 조건이 더 이상 유효하지 "
            "않은지 확인",
        "conditional.introduced": "- [ ] 도입 커밋: {sha} ({subject})",
        "conditional.run_guard": "- [ ] {guard} 실행해서 확인",
        "conditional.add_test": "- [ ] 회귀 테스트를 먼저 추가",
        "conditional.signoff": "- [ ] 이 영역을 잘 아는 사람에게 확인받기",

        "safe.title": "{path}의 불필요한 가드 제거",
        "safe.added": "이 코드는 {sha} ({subject})에서 추가되었습니다.",
        "safe.rationale": "이 코드가 필요했던 이유가 더 이상 유효하지 않아 제거해도 "
            "안전합니다.",
        "safe.evidence_header": "근거:",
        "safe.introducing_commit": "- 도입 커밋: {sha}",
        "safe.guarded_by": "- 관련 테스트: {guard}",
        "safe.no_test": "- 이 코드에 의존하는 테스트 없음",

        "unknown.title": "{path}:{start} 관련 질문",
        "unknown.body": "의도적으로 작성된 것 같은데, 왜 추가됐는지 찾지 못했습니다.",
        "unknown.closest": "가장 가까운 커밋: {sha} ({subject}, {day})",
        "unknown.author": "작성자: {who} <{mail}>",
        "unknown.notes_header": "조사 노트:",
        "unknown.limited": "조사 범위가 제한되었습니다: {scope}.",
        "unknown.scope_truncated": "히스토리 탐색이 중간에 끊김",
        "unknown.scope_cap": "후보 개수 상한에 도달함",
        "unknown.closing": "이거 아직 필요한지 아시는 분 있나요?",

        "common.unknown": "알 수 없음",
        "common.reason_unknown": "이유 불명",
        "common.no_subject": "제목 없음",
        "common.date_unknown": "날짜 알 수 없음",

        "scan.header": "주석 처리된 코드 후보 {count}건 ({path})",
        "scan.none": "{path} 아래에 주석 처리된 코드 블록이 없습니다.",
        "scan.none_capped": "{path}에 대해 나열된 후보가 없습니다. 후보 상한에서 "
                             "스캔이 멈춰 하나도 보고하지 못한 것이며, 블록이 "
                             "없다는 뜻이 아닙니다.",
        "scan.intro": "오래된 순입니다. 등급은 매기지 않았습니다. 각 항목을 판정하려면 "
                       "`/can-i-delete-this:check <path>:<start>-<end>`를 실행하세요.",
        "scan.look_first": "먼저 볼 것",
        "scan.item_meta": "{lines}줄, {age}일 전에 주석 처리됨",
        "scan.item_meta_unknown": "{lines}줄, 주석 처리한 커밋을 알 수 없음",
        "scan.body_truncated": "(본문 잘림, 나머지는 `git show {sha}`)",
        "scan.touched_by": "이 줄들을 건드린 커밋이 {count}개이고 가장 오래된 것을 보여줍니다",
        "scan.hints": "그 커밋에 대해: {hints}",
        "scan.scope": "스캔 범위: 전체 {total}개 파일 중 {scanned}개 "
                       "(미지원 {unsupported}개, vendored {vendored}개, 생성물 {generated}개, "
                       "용량 초과 {too_large}개, HEAD에 없음 {missing_at_head}개 건너뜀, "
                       "후보 상한 도달로 아예 열지 않음 {not_reached}개).",
        "scan.cap": "후보 상한 {cap}에 도달했습니다. 더 있을 수 있습니다.",
        "scan.boundary": "블록 주석(`/* ... */`)은 감지하지 않습니다.",
    },
}


def _resolve_lang(lang):
    """An unknown lang value falls back to English rather than erroring.

    A wrong language is a worse failure than an untranslated one only if
    it crashes, so this never raises: anything not in `_STRINGS` becomes
    `"en"`.
    """
    return lang if lang in _STRINGS else "en"


def _t(lang, key, **kwargs):
    """Look up `key` for `lang` (falling back to English), then format it.

    A key missing from a supported language's table falls back to the
    English text for that key rather than raising, so a partially
    translated future language degrades to English phrase by phrase
    instead of crashing.
    """
    lang = _resolve_lang(lang)
    template = _STRINGS[lang].get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def _top(trace_data, real_refs, all_refs):
    """Pick the candidate the artifact should describe, and how it was found.

    `real_refs` is `citation.real_introduction_refs(evidence)`: commit refs
    tagged `role: "introduced"` or carrying no role at all (see citation.py's
    module docstring). `all_refs` is `citation.commit_refs(evidence)`: every
    cited commit ref regardless of role. The two are equal for a verdict
    that never uses roles at all, or that only cites `introduced`/roleless
    commits; they diverge exactly when a verdict cites commits under roles
    like `"superseded"` or `"reference"` and nothing tagged `"introduced"` --
    the "not_introduction" status below exists for that case.

    Returns (candidate, status):

    - "cited": `candidate` is what `real_refs` cites, found by
      citation.find_cited in either introduction_candidates or
      blame_candidates. See citation.py for why the cited commit is not
      guaranteed to be in the first list: noise filtering can remove the
      real commit from introduction_candidates entirely (a merge, or a
      commit-wide cosmetic rewrite that still carried one real edit to
      this file), and SKILL.md's workflow then has the agent cite it out
      of blame_candidates anyway, after reading its diff.
    - "unresolved": `real_refs` is non-empty, but it names no commit in
      either list. verdict.py's schema only checks that a ref is a
      non-empty string, not that it names a real commit in this trace, so
      a stale or mistyped ref reaches here as a citation that resolves to
      nothing. `candidate` is {}. Substituting some other candidate here
      would be exactly the M2 misattribution this function exists to
      prevent, so callers must say the citation did not resolve, not guess
      a replacement.
    - "not_introduction": `real_refs` is empty but `all_refs` is not -- the
      verdict cited one or more commits, just none of them tagged as the
      real introduction (all were `superseded`/`reference`/`guard`/`risk`).
      `candidate` is {}. Falling through to "fallback" below and silently
      naming `introduction_candidates[0]` would be exactly the same M2
      misattribution the "unresolved" case above already guards against,
      just reached from a different direction, so this says so plainly
      instead of guessing.
    - "fallback": no citation was made at all (`all_refs` is empty too).
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
    if real_refs:
        found, _source = citation.find_cited(trace_data, real_refs)
        if found is not None:
            return found, "cited"
        return {}, "unresolved"
    if all_refs:
        return {}, "not_introduction"
    if cands:
        return cands[0], "fallback"
    return {}, "empty"


def _unresolved_citation_text(grade, target, refs, *, lang="en"):
    """Artifact text for a citation that names no commit in this trace.

    Keeps the artifact useful even though the attribution is unresolved:
    the grade, the target, and the cited ref(s) are still worth carrying,
    and the reader needs to know the attribution has not been verified
    rather than be handed a confident guess (see _top's "unresolved"
    branch for why guessing is exactly the bug this avoids).
    """
    unknown = _t(lang, "common.unknown")
    path = target.get("path", unknown)
    start = target.get("start", unknown)
    cited = ", ".join(refs) if refs else unknown
    return "\n".join([
        "{}: {}".format(_t(lang, "label.grade"), grade),
        "{}: {}:{}".format(_t(lang, "label.target"), path, start),
        "",
        _t(lang, "unresolved.cited", cited=cited),
        _t(lang, "unresolved.warning"),
    ])


def _not_introduction_text(grade, target, refs, *, lang="en"):
    """Artifact text for a verdict whose evidence cites commits, but none
    of them tagged as the real introduction (see citation.py's
    `real_introduction_refs`: every item was `role: "superseded"`,
    `"reference"`, `"guard"` or `"risk"`).

    Unlike `_unresolved_citation_text`, the cited commit(s) here do exist
    in this trace -- they are simply not what this artifact is meant to
    name. Silently substituting `introduction_candidates[0]` here would be
    the same M2 misattribution `_top`'s "unresolved" branch already
    guards against, just reached from evidence that resolves instead of
    evidence that doesn't, so this states the situation plainly instead
    of guessing, the same way `_unresolved_citation_text` does.
    """
    unknown = _t(lang, "common.unknown")
    path = target.get("path", unknown)
    start = target.get("start", unknown)
    cited = ", ".join(refs) if refs else unknown
    return "\n".join([
        "{}: {}".format(_t(lang, "label.grade"), grade),
        "{}: {}:{}".format(_t(lang, "label.target"), path, start),
        "",
        _t(lang, "not_introduction.cited", cited=cited),
        _t(lang, "unresolved.warning"),
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


def skeleton(grade, trace_data, evidence=None, *, lang="en"):
    """Return a fill-in-the-blank artifact for the agent to complete.

    `evidence` is the verdict's own `evidence` list (commit/pr/issue/test
    entries). Passing it lets `_top` prefer the candidate the verdict
    actually cites over the chronologically-oldest one; see `_top`'s
    docstring. It is optional and defaults to None so existing callers that
    have not been updated keep the previous (oldest-candidate) behavior.
    Only a commit cited with `role: "introduced"` or no role at all can win
    that preference (see citation.py's `real_introduction_refs`); a commit
    cited under any other role never names this artifact's keep-comment or
    checklist entry, even when it is the first or only commit in the list.

    `lang` selects the language of the chrome this function writes around
    the trace/verdict data (see the module docstring and `_STRINGS`);
    it defaults to `"en"` so existing callers keep the previous text.
    """
    target = trace_data.get("target", {})
    # real_refs is the narrower, role-aware set (citation.py's module
    # docstring has the rule): only these can resolve to "cited" below.
    # all_refs is every cited commit ref regardless of role, needed only
    # to tell "nothing was cited" (fallback to the oldest candidate is
    # honest there) apart from "something was cited, just not tagged as
    # the real introduction" (fallback would silently misattribute there).
    real_refs = citation.real_introduction_refs(evidence)
    all_refs = citation.commit_refs(evidence)
    top, status = _top(trace_data, real_refs, all_refs)

    if status == "unresolved":
        return _unresolved_citation_text(grade, target, real_refs, lang=lang)
    if status == "not_introduction":
        return _not_introduction_text(grade, target, all_refs, lang=lang)

    # Every field below is checked with isinstance() before use, not coerced
    # with str(). str(x) turns a missing/None date into "" or "None" and lets
    # it leak straight into the rendered text (e.g. "// KEEP: hotfix (None,
    # a3f8c21)"); isinstance() plus an explicit fallback keeps that from
    # happening when introduction_candidates is empty, as it is for F4-style
    # squash cases (see tests/test_trace_cases.py::test_reports_why_it_came_up_empty).
    raw_sha = top.get("sha")
    sha = raw_sha[:7] if isinstance(raw_sha, str) and raw_sha else _t(lang, "common.unknown")

    raw_subject = top.get("subject")
    subject = raw_subject if isinstance(raw_subject, str) and raw_subject else ""

    raw_date = top.get("date")
    day = raw_date[:10] if isinstance(raw_date, str) and raw_date else _t(lang, "common.date_unknown")

    tests = _tests(trace_data, raw_sha if isinstance(raw_sha, str) and raw_sha else None)
    guard = tests[0] if tests else None

    if grade == "danger":
        lines = [_t(lang, "danger.keep",
                    subject=subject or _t(lang, "common.reason_unknown"),
                    day=day, sha=sha)]
        if guard:
            lines.append(_t(lang, "danger.guard", guard=guard))
        else:
            lines.append(_t(lang, "danger.warning"))
        return "\n".join(lines)

    if grade == "conditional":
        guard_line = _t(lang, "conditional.run_guard", guard=guard) if guard \
            else _t(lang, "conditional.add_test")
        return "\n".join([
            _t(lang, "conditional.title", path=target.get("path"), start=target.get("start")),
            _t(lang, "conditional.condition"),
            _t(lang, "conditional.introduced", sha=sha,
               subject=subject or _t(lang, "common.unknown")),
            guard_line,
            _t(lang, "conditional.signoff"),
        ])

    if grade == "safe":
        guard_line = _t(lang, "safe.guarded_by", guard=guard) if guard \
            else _t(lang, "safe.no_test")
        return "\n".join([
            _t(lang, "safe.title", path=target.get("path")),
            "",
            _t(lang, "safe.added", sha=sha, subject=subject or _t(lang, "common.unknown")),
            _t(lang, "safe.rationale"),
            "",
            _t(lang, "safe.evidence_header"),
            _t(lang, "safe.introducing_commit", sha=sha),
            guard_line,
        ])

    if grade == "unknown":
        raw_author = top.get("author")
        who = raw_author if isinstance(raw_author, str) and raw_author else _t(lang, "common.unknown")
        raw_mail = top.get("author_email")
        mail = raw_mail if isinstance(raw_mail, str) and raw_mail else _t(lang, "common.unknown")

        lines = [
            _t(lang, "unknown.title", path=target.get("path"), start=target.get("start")),
            "",
            _t(lang, "unknown.body"),
            _t(lang, "unknown.closest", sha=sha,
               subject=subject or _t(lang, "common.no_subject"), day=day),
            _t(lang, "unknown.author", who=who, mail=mail),
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
            lines.append(_t(lang, "unknown.notes_header"))
            lines.extend("- {}".format(n) for n in note_lines)

        limits = trace_data.get("limits")
        if isinstance(limits, dict):
            scope_flags = []
            if limits.get("truncated"):
                scope_flags.append(_t(lang, "unknown.scope_truncated"))
            if limits.get("candidate_cap_reached"):
                scope_flags.append(_t(lang, "unknown.scope_cap"))
            if scope_flags:
                lines.append("")
                lines.append(_t(lang, "unknown.limited", scope="; ".join(scope_flags)))

        lines.append("")
        lines.append(_t(lang, "unknown.closing"))
        return "\n".join(lines)

    raise ValueError("unsupported grade: {!r}".format(grade))


def scan_checklist(scan_data, *, lang="en"):
    """A markdown checklist of a scan's candidates, ready to paste into an
    issue or a pull request.

    Deliberately not a report and deliberately not graded. The scan found
    blocks and read the commits behind them; deciding what to do with one
    means running the single-target workflow on it, which is what the
    closing line tells the reader.

    Checkbox syntax is written literally. In 0.2.2 an escape sequence built
    it instead, Python read the digits as octal, and every shipped version
    had broken checkboxes.
    """
    lang = _resolve_lang(lang)
    limits = scan_data.get("limits") or {}
    candidates = scan_data.get("candidates") or []
    path = (scan_data.get("target") or {}).get("path") or "."

    scanned = limits.get("files_scanned") or 0
    unsupported = limits.get("files_skipped_unsupported") or 0
    vendored = limits.get("files_skipped_vendored") or 0
    generated = limits.get("files_skipped_generated") or 0
    too_large = limits.get("files_skipped_too_large") or 0
    missing_at_head = limits.get("files_missing_at_head") or 0
    # Files `ls-files` listed but the scan never opened, because the
    # candidate cap stopped it first. Counted in the total so the scope
    # sentence means "of everything tracked under this path", not "of
    # everything we happened to reach".
    not_reached = limits.get("files_not_reached") or 0
    total = (scanned + unsupported + vendored + generated + too_large
             + missing_at_head + not_reached)

    lines = []
    if candidates:
        lines.append("## " + _t(lang, "scan.header", count=len(candidates),
                                 path=path))
        lines.append("")
        lines.append(_t(lang, "scan.intro"))
        lines.append("")
    elif limits.get("candidate_cap_reached"):
        # An empty list under a reached cap (a cap of 0) is "nothing was
        # reported", not "nothing is there". Saying the latter would be a
        # claim about files the scan never looked at.
        lines.append("## " + _t(lang, "scan.none_capped", path=path))
        lines.append("")
    else:
        lines.append("## " + _t(lang, "scan.none", path=path))
        lines.append("")

    for candidate in candidates:
        target = "{}:{}-{}".format(candidate.get("path", ""),
                                    candidate.get("start", ""),
                                    candidate.get("end", ""))
        commit = candidate.get("commented_out_by") or {}
        prefix = "- [ ] "
        if candidate.get("look_first"):
            prefix += "**" + _t(lang, "scan.look_first") + "** "
        if commit.get("age_days") is None:
            meta = _t(lang, "scan.item_meta_unknown",
                       lines=candidate.get("lines", 0))
        else:
            meta = _t(lang, "scan.item_meta", lines=candidate.get("lines", 0),
                       age=commit["age_days"])
        lines.append("{}`{}` ({})".format(prefix, target, meta))

        sha = commit.get("sha") or ""
        if sha:
            lines.append("      `{}` {}".format(sha[:7],
                                                 commit.get("subject") or ""))
        body = (commit.get("body") or "").strip()
        if body:
            first = body.splitlines()[0]
            lines.append("      > " + first)
            if commit.get("body_truncated"):
                lines.append("      > " + _t(lang, "scan.body_truncated",
                                              sha=sha[:7]))
        if (candidate.get("touched_by_commits") or 0) > 1:
            lines.append("      " + _t(lang, "scan.touched_by",
                                        count=candidate["touched_by_commits"]))
        # What blame returned is the oldest commit owning these lines,
        # which is not always the commit that commented them out. The
        # hints scan.py already read say when that commit looks like a
        # sweep or a formatter, so a reader sees the doubt on the same
        # line as the attribution instead of only in the JSON.
        raw_hints = commit.get("hints")
        hints = [h for h in (raw_hints or []) if isinstance(h, str) and h.strip()] \
            if isinstance(raw_hints, list) else []
        if hints:
            lines.append("      " + _t(lang, "scan.hints",
                                        hints="; ".join(hints)))

    lines.append("")
    lines.append(_t(lang, "scan.scope", scanned=scanned, total=total,
                     unsupported=unsupported, vendored=vendored,
                     generated=generated, too_large=too_large,
                     missing_at_head=missing_at_head,
                     not_reached=not_reached))
    if limits.get("candidate_cap_reached"):
        lines.append(_t(lang, "scan.cap", cap=limits.get("max_candidates")))
    lines.append(_t(lang, "scan.boundary"))
    return "\n".join(lines)


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
    ap.add_argument("--trace")
    ap.add_argument("--verdict")
    ap.add_argument("--scan", help="a scan.py JSON file; emits the candidate "
                                    "checklist instead of a verdict artifact")
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--lang", default="en", help="language for the artifact's own "
                    "wording (en, ko; unknown values fall back to en). Data read "
                    "from git or the verdict -- shas, paths, subjects, authors, "
                    "dates -- is never translated.")
    args = ap.parse_args()

    if args.scan:
        with open(args.scan, encoding="utf-8") as fh:
            content = scan_checklist(json.load(fh), lang=args.lang)
    elif args.trace and args.verdict:
        with open(args.trace, encoding="utf-8") as fh:
            t = json.load(fh)
        with open(args.verdict, encoding="utf-8") as fh:
            v = json.load(fh)
        content = v.get("artifact", {}).get("content") or skeleton(
            v.get("grade", "unknown"), t, v.get("evidence"), lang=args.lang)
    else:
        ap.error("pass either --scan, or both --trace and --verdict")

    print(content)
    if args.copy:
        tool = to_clipboard(content)
        print("\n[copied with {}]".format(tool) if tool
              else "\n[no clipboard tool found; copy the text above]")


if __name__ == "__main__":
    main()
