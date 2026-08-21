"""Render a trace plus verdict into one self-contained HTML file.

No CDN, no fonts, no libraries. The timeline is flexbox and borders so the
page renders identically offline and in both colour schemes.

The whole point of the page is to make "blame pointed at the wrong commit"
visible at a glance. But trace.py cannot know which candidate is real (the
verdict deciding that is written after the tracer runs), so this module
takes its cue from the verdict's own evidence, not from list position or
list membership alone:

- A candidate renders bold and coloured, tagged "real introduction", when
  its sha matches a `commit` entry in `verdict["evidence"]` (matched on
  prefix, since evidence refs are usually short shas), whether that
  candidate lives in `introduction_candidates` or only in
  `blame_candidates` (see `citation.py` for why a cited commit can live in
  either list -- the short version: noise filtering can remove the real
  commit from `introduction_candidates` entirely, and the workflow this
  skill teaches then has the agent cite it out of `blame_candidates`
  anyway, after reading its diff). Every other introduction candidate
  renders as a plain row: it survived noise filtering, but the verdict did
  not cite it.
- A `blame_candidates` entry renders greyed-out and struck through, with
  the noise category that disqualified it, when `noise.is_noise` is true
  and the verdict did not cite it. A blame candidate that scored as
  not-noise (this happens: breadth or whitespace checks can clear a commit
  that still is not the real introduction) renders as a plain row instead,
  never struck through.
- When the verdict cites a commit that blame_candidates flags noisy, both
  facts render on the *same* row: bold "real introduction" plus the noise
  category as a second tag. This is not a contradiction to hide -- a
  hand-resolved merge commit (N9) is filtered on its parent count and can
  still be where a line was introduced -- and the page should say so
  rather than pick one fact and drop the other. The same commit never gets
  a second, separate noise row once it has been rendered as real.
- Any row, of any of those kinds, also carries its `hints`: vocabulary its
  subject matched, rendered as a claim rather than a finding (see
  `_hints_html`). Since 0.7.0 a subject filters nothing, so the commit
  whose subject looks like a PR title is an ordinary candidate on this
  page; without the hint the reader would see no reason to distrust what
  its subject says.

A reader should not need to read any prose to see which commit is the
answer and which one git blame lied about, but this module also must not
present a guess as fact: a candidate with no evidence behind it is neither
bold nor crossed out.

Every piece of UI chrome below -- badge labels, card headers, the dot
legend, tag text, disclosures, and so on -- is looked up in `_STRINGS`
by `lang` (see that dict's docstring). SHAs, paths, commit subjects,
author names and dates are data read from the trace or the verdict and are
never translated; only the words this module itself writes around that
data are.
"""

import argparse
import html
import json
import os
import shlex
import tempfile

import citation

# Colour is a function of grade, not of language, so it is kept separate
# from the label text in _STRINGS below.
#
# Each grade owns one hue (foreground + wash) for both colour schemes. This
# is the *only* place a hex value is chosen; render() writes the four values
# for the active grade into custom properties on <body> (see the "grade-fg"
# and "grade-wash" derivation in _CSS), and every rule in _CSS that used to
# branch on grade now reads var(--grade-fg)/var(--grade-wash) once instead.
# "unknown" has no hue of its own -- it points at the neutral --muted/--card
# variables already defined in _CSS, so an inconclusive report stays grey
# rather than borrowing a colour that would imply a verdict.
_GRADE_HUES = {
    "danger": {
        "fg_light": "#A32B22", "wash_light": "#FBEAE8",
        "fg_dark": "#F08A80", "wash_dark": "#351916",
    },
    "conditional": {
        "fg_light": "#8A5A0B", "wash_light": "#FBF1DF",
        "fg_dark": "#DCA83C", "wash_dark": "#2E2412",
    },
    "safe": {
        "fg_light": "#1F7A4C", "wash_light": "#E6F4EC",
        "fg_dark": "#5FC48D", "wash_dark": "#12281C",
    },
    "unknown": {
        "fg_light": "var(--muted)", "wash_light": "var(--card)",
        "fg_dark": "var(--muted)", "wash_dark": "var(--card)",
    },
}

# Every piece of text this module writes around the data it renders, keyed
# by language then by a dotted string key. This is a plain data lookup, not
# gettext: adding a third language means adding a third top-level key with
# every key of `en` translated, not touching any function below. `en` is
# the default and the fallback target (see `_resolve_lang`), so its text
# must stay exactly what shipped before this table existed -- the existing
# test suite calls `render()` with no `lang` argument and pins the exact
# HTML that produces.
#
# Keys are grouped by where they render: `badge.*` is the grade badge;
# `why.*` explains how a candidate was found; `tag.*` is the small pill on
# a timeline row; `card.*` is a card's header; `legend.*` is the dot-legend
# list; `hint.*`/`warn.*`/`history.*` are the smaller disclosures under the
# History card; `button.*` is the copy button and its JS feedback text;
# `chrome.*` is everything else (the target-line phrase in <title>/<h1>,
# and the "none"/"no history" fallbacks).
_STRINGS = {
    "en": {
        "badge.danger": "Do not delete",
        "badge.conditional": "Delete only if",
        "badge.safe": "Safe to delete",
        "badge.unknown": "Inconclusive",

        "why.blame": "found via blame",
        "why.pickaxe": "found via pickaxe (blame missed it)",
        "why.line-history": "found via line history",
        "why.follow": "found via rename-follow",
        "why.cited": "cited by the agent from reading history directly; "
                     "not found by blame, pickaxe or line-history",

        "tag.real": "real introduction",
        "tag.also_noise": "also flagged noise",
        "hints.prefix": "subject claims",
        "tag.blame_pointed": "blame pointed here",
        "tag.revert_chain": "revert chain",

        "card.evidence": "Evidence",
        "card.conditions": "Conditions",
        "card.next_step": "Next step ({kind})",
        "card.history": "History: blame vs. the real introduction",
        "card.notes": "Notes and limits",

        "legend.real": "the commit the verdict cites as the real introduction",
        "legend.noise": "scored as noise, not cited",
        "legend.plain": "a candidate, neither cited nor noise",
        "legend.revert": "part of a revert/reapply chain",

        "hint.co_changed": "Also touched in the introducing commit: {paths}",
        "hint.co_changed_capped": "Also touched in the introducing commit "
            "({shown} of {total} shown, capped per commit; rerun with "
            "--max-co-changed to see more): {paths}",
        "chrome.no_history": "No history found.",
        "chrome.none": "none",
        "chrome.line_suffix": "line {line_range}",

        "warn.truncated": "History walk was truncated at {max_commits} commits "
                           "(since {since}). Older introducing commits may exist "
                           "but were not reached.",
        "warn.candidate_cap": "Candidate cap of {max_candidates} was reached. "
                               "This investigation stopped collecting candidates "
                               "before exhausting the history; treat the result "
                               "as partial, not conclusive.",

        "history.collapse_summary": "Other candidates from the search "
                                     "({count} commit{plural})",

        "button.copy": "Copy",
        "button.copied": "Copied",

        "card.snippet": "Code",
        "snippet.unavailable.missing-at-head": "This file no longer exists at "
            "HEAD, so the target lines cannot be shown.",
        "snippet.unavailable.out-of-range": "Line {start}-{end} is past the "
            "end of this file at HEAD.",
        "snippet.unavailable.binary": "This file is binary at HEAD; its "
            "contents cannot be shown as text.",
        "snippet.unavailable.irregular-line-break": "This file contains a "
            "character that makes its line numbers unreliable; the "
            "target lines cannot be shown.",
        "snippet.unavailable.generic": "The target lines could not be read "
            "from this file at HEAD.",

        "activity.last_touch.lines": "Target lines last touched {date} ({sha})",
        "activity.last_touch.file": "File last touched {date} ({sha}); "
            "target-line history was unavailable",
        "activity.commits_last_year": "{count} commit(s) to this file in "
            "the last year",
        "activity.top_authors": "Main authors: {names}",

        "card.repro": "Reproduce this",

        "card.lifecycle": "Why it existed",
        "role.introduced": "Introduced",
        "role.superseded": "Superseded",

        "card.isolation": "Current isolation",
        "isolation.guard_label": "guard{plural}",
        "isolation.reference_label": "mention{plural}",

        "card.risk": "Residual risk",
    },
    "ko": {
        "badge.danger": "삭제 금지",
        "badge.conditional": "조건부 삭제",
        "badge.safe": "삭제 가능",
        "badge.unknown": "판단 불가",

        "why.blame": "blame으로 찾음",
        "why.pickaxe": "pickaxe로 찾음 (blame이 놓친 커밋)",
        "why.line-history": "line-history로 찾음",
        "why.follow": "rename 추적으로 찾음",
        "why.cited": "에이전트가 히스토리를 직접 읽고 인용함; "
                     "blame·pickaxe·line-history 어디에도 없었음",

        "tag.real": "실제 도입 커밋",
        "tag.also_noise": "노이즈로도 채점됨",
        "hints.prefix": "제목이 주장하는 것",
        "tag.blame_pointed": "blame이 지목한 커밋",
        "tag.revert_chain": "revert 체인",

        "card.evidence": "근거",
        "card.conditions": "조건",
        "card.next_step": "다음 행동 ({kind})",
        "card.history": "히스토리: blame이 지목한 커밋 vs 실제 도입 커밋",
        "card.notes": "조사 노트와 제한사항",

        "legend.real": "검증이 실제 도입 커밋으로 지목한 커밋",
        "legend.noise": "노이즈로 채점되어 인용되지 않은 커밋",
        "legend.plain": "인용되지도 노이즈로도 채점되지 않은 후보",
        "legend.revert": "revert/reapply 체인의 일부",

        "hint.co_changed": "도입 커밋에서 함께 변경된 파일: {paths}",
        "hint.co_changed_capped": "도입 커밋에서 함께 변경된 파일 (커밋당 상한으로 "
            "총 {total}개 중 {shown}개만 표시; 더 보려면 --max-co-changed로 "
            "다시 실행): {paths}",
        "chrome.no_history": "히스토리를 찾지 못했습니다.",
        "chrome.none": "없음",
        "chrome.line_suffix": "{line_range}번째 줄",

        "warn.truncated": "히스토리 탐색이 {since} 이후 {max_commits}개 커밋에서 "
                           "중단되었습니다. 더 오래된 도입 커밋이 있을 수 있지만 "
                           "확인하지 못했습니다.",
        "warn.candidate_cap": "후보 개수 상한({max_candidates})에 도달했습니다. "
                               "히스토리를 다 훑기 전에 후보 수집이 멈췄으니, 이 "
                               "결과는 확정이 아니라 부분적인 결과로 봐주세요.",

        "history.collapse_summary": "검색된 다른 후보 ({count}개 커밋)",

        "button.copy": "복사",
        "button.copied": "복사됨",

        "card.snippet": "코드",
        "snippet.unavailable.missing-at-head": "이 파일은 HEAD에 더 이상 없어서 "
            "대상 줄을 보여줄 수 없습니다.",
        "snippet.unavailable.out-of-range": "{start}-{end}번째 줄은 HEAD 기준 "
            "파일 끝을 넘어섰습니다.",
        "snippet.unavailable.binary": "이 파일은 HEAD 기준 바이너리라 텍스트로 "
            "보여줄 수 없습니다.",
        "snippet.unavailable.irregular-line-break": "이 파일에 줄 번호를 믿을 수 "
            "없게 만드는 문자가 있어, 대상 줄을 보여줄 수 없습니다.",
        "snippet.unavailable.generic": "HEAD 기준으로 대상 줄을 읽을 수 없습니다.",

        "activity.last_touch.lines": "대상 줄 최근 수정: {date} ({sha})",
        "activity.last_touch.file": "파일 최근 수정: {date} ({sha}); "
            "대상 줄 단위 히스토리는 확인하지 못했습니다",
        "activity.commits_last_year": "최근 1년간 이 파일에 커밋 {count}개",
        "activity.top_authors": "주요 작성자: {names}",

        "card.repro": "재현 명령어",

        "card.lifecycle": "존재했던 이유",
        "role.introduced": "도입",
        "role.superseded": "대체됨",

        "card.isolation": "현재 고립도",
        "isolation.guard_label": "가드",
        "isolation.reference_label": "언급",

        "card.risk": "잔존 위험",
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


def _why_label(lang, why):
    lang = _resolve_lang(lang)
    key = "why." + str(why)
    return _STRINGS[lang].get(key) or _STRINGS["en"].get(key) or why


_CSS = """
:root { color-scheme: light dark; --bg:#FCFCFB; --fg:#1A1D21; --muted:#6E7378;
        --line:#E5E6E4; --card:#F7F7F5; --code:#EFEFEC;
        --warn-fg:#A32B22; --warn-bg:#FBEAE8; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14161A; --fg:#E8E9EA; --muted:#8B9096; --line:#2A2E34;
          --card:#1B1E23; --code:#22262C;
          --warn-fg:#F08A80; --warn-bg:#351916; }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
/* --grade-fg/--grade-wash are derived here, on body, not on :root: a
   custom property's var() references resolve against the same element's
   own cascaded values, not lazily against whatever a descendant later
   defines, so this rule must live on the exact element that carries the
   --grade-*-light/-dark values render() writes inline (see render()'s
   root_style comment for why those are inline on body rather than on
   <html> in the first place). Every other rule below reads var(--grade-fg)
   / var(--grade-wash) once instead of branching on grade. */
body { --grade-fg: var(--grade-fg-light); --grade-wash: var(--grade-wash-light);
       margin:0; padding:2.5rem 1.25rem 3rem; background:var(--bg); color:var(--fg);
       font:15px/1.6 -apple-system, BlinkMacSystemFont, "Pretendard Variable", Pretendard,
       "Apple SD Gothic Neo", system-ui, "Segoe UI", "Malgun Gothic", sans-serif;
       word-break: keep-all; }
@media (prefers-color-scheme: dark) {
  body { --grade-fg: var(--grade-fg-dark); --grade-wash: var(--grade-wash-dark); }
}
main { max-width: 62rem; margin: 0 auto; }
h1 { font-size:.8rem; font-weight:500; color:var(--muted); margin:0 0 1rem;
     letter-spacing:.01em; }
h1 .path { font-weight:600; color:var(--fg);
           font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
           word-break: break-word; }
.verdict { background:var(--grade-wash); border-radius:14px;
           padding:1.4rem 1.6rem 1.6rem; margin:0 0 1.75rem; }
.badge { display:block; font-weight:800; font-size:1.85rem; line-height:1.15;
         letter-spacing:-.01em; color:var(--grade-fg); margin:0 0 .5rem; }
.sub { color:var(--fg); margin:0; max-width:48rem; font-size:1.05rem; line-height:1.55; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:1.1rem 1.35rem; margin:0 0 1.25rem; }
.card-next { border-left:3px solid var(--grade-fg); }
.section { padding:1.1rem 0 0; margin:0 0 1.25rem; border-top:1px solid var(--line); }
.section-notes { color:var(--muted); font-size:.92rem; }
.card > strong, .section > strong { display:block; font-size:.75rem; text-transform:uppercase;
                 letter-spacing:.06em; color:var(--muted); margin-bottom:.6rem; }
.timeline { display:flex; flex-direction:column; position:relative; z-index:0; }
/* The connecting line is drawn per row, not as one line across the whole
   container, because a row's height is content-dependent (a noise row's
   signals text, a real row's meta line) while the dot's distance from its
   OWN row's top edge is not (align-items:flex-start pins date/dot to the
   top of the row regardless of how tall the entry column grows). A
   container-spanning line sized off guessed top/bottom insets overshoots
   past the last dot whenever the last row carries that kind of trailing
   content -- verified by rendering a sample and reading its computed
   layout, not by inspection alone. Splitting the line into one segment per
   row avoids the guess entirely: a row that has a later row (":has(~
   .row)") draws its full height; a row with no later row draws only from
   its own top down to its own dot; a row with no earlier row draws only
   from its own dot down to its own bottom; a row that is both (the only
   row) draws nothing. Stacked together those segments are exactly [first
   dot, last dot], never outside that range, and stay continuous
   regardless of how tall any individual row's content happens to be.
   ":has(~ .row)" rather than ":last-child" on purpose: the collapsed
   disclosure element the History card appends after the always-visible
   rows (see render()) is itself a later sibling, so ":last-child" never
   matches any row once a timeline collapses, and every visible row would
   wrongly draw as a "middle" one, overshooting the last dot by the same
   1.6rem this comment's sibling rules are careful to stop at otherwise --
   caught by rendering the History-collapse sample and reading its
   computed layout. (Deliberately not spelling out that element's tag name
   here: it would land inside the page's own style block verbatim and make
   this project's own "no such element in a short trace" test fail on a
   plain substring match against a code comment, not against a real
   collapsed disclosure -- caught the same way, by running the tests.)
   1.6rem approximates a row's own padding-top plus half the dot glyph's
   line height -- the fixed part of a row's height that does not depend on
   what the entry column holds. */
.row:not(:first-child):has(~ .row)::before {
  content:""; position:absolute; z-index:-1; left:calc(7.7rem - 1px);
  top:0; height:100%; width:2px; background:var(--line);
}
.row:first-child:has(~ .row)::before {
  content:""; position:absolute; z-index:-1; left:calc(7.7rem - 1px);
  top:1.6rem; height:calc(100% - 1.6rem); width:2px; background:var(--line);
}
.row:not(:first-child):not(:has(~ .row))::before {
  content:""; position:absolute; z-index:-1; left:calc(7.7rem - 1px);
  top:0; height:1.6rem; width:2px; background:var(--line);
}
/* .row.real also carries its own margin-bottom (see the "real" rules
   further down) to separate its highlighted wash from the row after it.
   That margin sits outside the border box a percentage height resolves
   against, so without this the line stops short of the next row's top by
   exactly that margin. Bridge it on both shapes a non-last real row can
   take (leading the timeline, or not, if the verdict cites more than one
   commit as real) so the line does not visibly break there. */
.row.real:first-child:has(~ .row)::before { height: calc(100% - 1.6rem + .35rem); }
.row.real:not(:first-child):has(~ .row)::before { height: calc(100% + .35rem); }
.row { display:flex; gap:1rem; align-items:flex-start; padding:.7rem 0;
       border-bottom:1px dashed var(--line); overflow-x:auto; position:relative; }
.row:last-child { border-bottom:0; }
.date { color:var(--muted); white-space:nowrap; width:6rem; flex:0 0 6rem; padding-top:.15rem;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        word-break: break-word; }
.dot { width:1.4rem; flex:0 0 1.4rem; text-align:center; padding-top:.1rem; font-weight:700;
       font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.entry { min-width:0; flex:1; }
.subject { word-break:break-word;
           font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.row.real { background:var(--grade-wash); border-radius:8px; margin:0 -0.5rem .35rem;
            padding:.8rem 0.5rem; border-bottom:none; }
.row.real .dot { color:var(--grade-fg); font-size:1.15em; }
.row.real .subject { font-weight:800; color:var(--fg); }
.row.noise .dot { color:var(--muted); }
.row.noise .subject { color:var(--muted); text-decoration:line-through;
                      text-decoration-color:var(--muted); text-decoration-thickness:1px; }
.row.revert .dot { color:var(--muted); }
.meta { color:var(--muted); font-size:.85rem; margin-top:.2rem; }
.tag { display:inline-block; font-size:.7rem; font-weight:700; text-transform:uppercase;
       letter-spacing:.03em; border-radius:4px; padding:.1rem .4rem; margin-left:.4rem;
       vertical-align:middle; }
.tag.real { background:var(--grade-wash); color:var(--grade-fg); border:1px solid var(--grade-fg); }
.tag.noise { background:var(--code); color:var(--muted); border:1px solid var(--line); }
.signals { color:var(--muted); font-size:.8rem; margin-top:.15rem; }
.hints { color:var(--muted); font-size:.8rem; margin-top:.15rem; font-style:italic; }
pre { background:var(--code); padding:.9rem 1rem; border-radius:8px; overflow-x:auto;
      margin:.6rem 0 0; white-space:pre-wrap; word-break:break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
button { font:inherit; font-size:.85rem; cursor:pointer; border:1px solid var(--line);
         background:var(--bg); color:var(--fg); border-radius:6px;
         padding:.3rem .75rem; float:right; }
button:hover { border-color:var(--grade-fg); }
ul { margin:.4rem 0 0; padding-left:1.2rem; }
li { margin:.15rem 0; }
ul.checklist { list-style:none; padding-left:0; }
ul.checklist li { position:relative; padding-left:1.7rem; margin:.4rem 0; }
ul.checklist li::before { content:"☐"; position:absolute; left:0; top:0;
                          color:var(--grade-fg); font-size:1rem; line-height:1.4; }
.warn { color:var(--warn-fg); background:var(--warn-bg); border-radius:8px;
        padding:.6rem .85rem; margin:.7rem 0 0; font-size:.9rem; }
.warn:first-child { margin-top:0; }
/* .risk reuses the exact --warn-fg/--warn-bg pair .warn already uses above,
   not a new colour, per the design note that the warning treatment already
   exists in this stylesheet. It renders as its own card (not a plain .warn
   paragraph) because a risk block carries a header plus a list of hazards,
   not one sentence, and it must sit near the verdict, not at the bottom, so
   a `safe` grade with a residual risk cannot be read as risk-free. */
.risk { background:var(--warn-bg); color:var(--warn-fg); border-radius:12px;
        padding:1rem 1.2rem; margin:0 0 1.25rem; }
.risk > strong { display:block; font-size:.75rem; text-transform:uppercase;
                 letter-spacing:.06em; margin-bottom:.5rem; color:var(--warn-fg); }
.risk ul { margin:.2rem 0 0; padding-left:1.2rem; color:var(--warn-fg); }
.risk li { margin:.25rem 0; }
/* The lifetime arc: a short chain of steps (introduced, then superseded)
   joined by an arrow, compact rather than a paragraph, since the arc's
   whole point is that a reader sees the shape of the argument at a glance. */
.arc { display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin-top:.5rem; }
.arc-step { display:inline-flex; align-items:baseline; gap:.4rem; }
.arc-arrow { color:var(--muted); font-weight:700; }
.tag.role { background:var(--code); color:var(--muted); border:1px solid var(--line); }
/* Isolation figures render as small stat tiles, not prose, so a zero count
   is a number a reader sees immediately rather than a fact buried in a
   sentence. */
.stats { display:flex; gap:1.75rem; margin-top:.5rem; }
.stat { display:flex; flex-direction:column; }
.stat-num { font-size:1.5rem; font-weight:800; color:var(--fg); line-height:1.1; }
.stat-label { font-size:.72rem; color:var(--muted); text-transform:uppercase;
              letter-spacing:.05em; margin-top:.2rem; }
.hint { color:var(--muted); font-size:.85rem; margin:.4rem 0 0; }
code { background:var(--code); border-radius:4px; padding:.05rem .3rem;
       font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       word-break:break-word; }
ul.legend { list-style:none; padding:0; margin:.6rem 0 0; display:flex; flex-wrap:wrap;
            gap:.4rem 1.25rem; color:var(--muted); font-size:.8rem; }
ul.legend li { display:flex; align-items:center; gap:.35rem; }
ul.legend .ldot { font-weight:700;
                   font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
ul.legend .ldot.real { color:var(--grade-fg); }
ul.legend .ldot.noise { color:var(--muted); text-decoration:line-through; }
ul.legend .ldot.revert { color:var(--muted); }
details.history-more { margin-top:.5rem; }
details.history-more > summary { cursor:pointer; color:var(--muted); font-size:.85rem;
                                  padding:.5rem .1rem; list-style:none;
                                  display:flex; align-items:center; gap:.4rem;
                                  border-radius:6px; }
details.history-more > summary::-webkit-details-marker { display:none; }
details.history-more > summary::before { content:"▸"; display:inline-block;
                                          font-size:.75rem; transition:transform .12s; }
details.history-more[open] > summary::before { content:"▾"; }
details.history-more > summary:hover { color:var(--fg); }
details.history-more > summary:focus-visible { outline:2px solid var(--grade-fg);
                                                outline-offset:2px; }
details.history-more > .timeline { margin-top:.3rem; }
.snippet-card { margin:0 0 1.75rem; }
.snippet { overflow-x:auto; border-radius:8px; background:var(--code);
           font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
           font-size:.82rem; line-height:1.6; }
.snippet-row { display:flex; white-space:pre; border-left:3px solid transparent;
               padding:0 .9rem 0 .6rem; }
.snippet-row.target { border-left-color:var(--grade-fg); background:var(--grade-wash); }
.snippet-num { color:var(--muted); width:2.6rem; flex:0 0 2.6rem; text-align:right;
               padding-right:.9rem; user-select:none; }
.snippet-code { color:var(--fg); }
.snippet-unavailable { color:var(--muted); font-size:.9rem; margin:.3rem 0 0; }
ul.activity { list-style:none; padding:0; margin:0 0 .8rem; display:flex; flex-wrap:wrap;
              gap:.4rem 1.25rem; color:var(--muted); font-size:.85rem; }
ul.activity li { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
details.repro { margin-top:1.75rem; padding-top:1.1rem; border-top:1px solid var(--line); }
details.repro > summary { cursor:pointer; color:var(--muted); font-size:.8rem;
                           text-transform:uppercase; letter-spacing:.06em;
                           list-style:none; padding:.2rem 0; }
details.repro > summary::-webkit-details-marker { display:none; }
details.repro > summary:hover { color:var(--fg); }
details.repro > summary:focus-visible { outline:2px solid var(--grade-fg);
                                         outline-offset:2px; }
details.repro > button { margin-top:.6rem; }
details.repro > pre { white-space:pre; }
"""

_JS_TEMPLATE = """
document.addEventListener('click', function (e) {{
  var b = e.target.closest('[data-copy]');
  if (!b) return;
  var text = document.getElementById(b.getAttribute('data-copy')).textContent;
  var done = function () {{
    var old = b.textContent; b.textContent = '{copied}';
    setTimeout(function () {{ b.textContent = old; }}, 1200);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(done, function () {{}});
  }}
}});
"""


def _e(value):
    """Escape any value for safe embedding in HTML text or attributes."""
    return html.escape(str(value), quote=True)


def _day(iso):
    return _e(str(iso)[:10])


def _short(sha):
    return _e(str(sha)[:7])


def _real_row(candidate, *, noise=None, lang="en"):
    """The row for the commit the verdict cites as the real introduction.

    `candidate` can come from either candidate list: introduction_candidates
    (carries why/author_email/files_changed) or blame_candidates (carries
    only sha/subject/date/author/noise). Both shapes are handled here
    rather than forcing every caller to pre-normalize, since this is the
    one place both shapes ever need to render as "the answer".

    `noise` is that same candidate's own noise verdict, when known. When
    `noise["is_noise"]` is true, the cited commit is both the real
    introduction and a commit noise.py would have flagged on its own --
    exactly the situation noise-catalog.md documents (a hand-resolved
    merge, filtered on its parent count, whose diff nonetheless introduced
    the target line). Both facts render
    on this one row; nothing about this candidate is ever rendered as a
    second, separate noise row elsewhere (see render()).
    """
    why = candidate.get("why") or "blame"
    why_label = _why_label(lang, why)
    author = _e(candidate.get("author", ""))
    email = candidate.get("author_email")
    who = "{} &lt;{}&gt;".format(author, _e(email)) if email else author

    noise_html = ""
    if noise and noise.get("is_noise"):
        tag_text = _t(lang, "tag.also_noise")
        category = noise.get("category")
        if category:
            tag_text += ", " + str(category)
        signals = noise.get("signals") or []
        signals_html = ""
        if signals:
            signals_html = '<div class="signals">{}</div>'.format(
                "; ".join(_e(s) for s in signals))
        noise_html = '<span class="tag noise">{}</span>{}'.format(_e(tag_text), signals_html)

    return (
        '<div class="row real">'
        '<span class="date">{date}</span>'
        '<span class="dot">&#9679;</span>'
        '<span class="entry">'
        '<span class="subject">{sha} {subject}</span>'
        '<span class="tag real">{real_tag}</span>'
        '{noise}{hints}'
        '<div class="meta">{who} &middot; {why}</div>'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        real_tag=_e(_t(lang, "tag.real")),
        noise=noise_html,
        hints=_hints_html(candidate, noise=noise, lang=lang),
        who=who,
        why=_e(why_label),
    )


def _plain_row(candidate, *, show_why=False, lang="en"):
    """A candidate that is neither the verdict's cited real introduction
    nor scored as noise: found along the way, cited by nothing.
    """
    why = candidate.get("why", "")
    why_label = _why_label(lang, why)
    meta_html = ""
    if show_why:
        meta_html = '<div class="meta">{author} &lt;{email}&gt; &middot; {why}</div>'.format(
            author=_e(candidate.get("author", "")),
            email=_e(candidate.get("author_email", "")),
            why=_e(why_label),
        )
    return (
        '<div class="row">'
        '<span class="date">{date}</span>'
        '<span class="dot">&#9675;</span>'
        '<span class="entry">'
        '<span class="subject">{sha} {subject}</span>'
        '{hints}{meta}'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        hints=_hints_html(candidate, lang=lang),
        meta=meta_html,
    )


def _hints_html(candidate, *, noise=None, lang="en"):
    """Vocabulary the subject matched, rendered as a claim rather than a
    finding.

    Hints never filter (see noise.py), so a candidate carrying one is still
    on the page and still the reader's to judge. Showing them matters most
    on rows that are *not* noise: before 0.7.0 a PR-title-shaped subject
    over hundreds of files was filtered, and the row explaining itself was
    a noise row. Now that commit is an ordinary candidate, and without this
    the page would show it with no indication of why its subject cannot be
    taken at face value.
    """
    # Three shapes reach this function: a blame candidate (hints nested
    # under its own `noise`), an introduction candidate (hints at the top
    # level, since `_describe` carries no signals), and the cited real row
    # (candidate from `introduction_candidates`, noise verdict passed in
    # separately by `render()` from the matching blame entry).
    hints = (candidate.get("noise") or {}).get("hints") or []
    if not hints:
        hints = candidate.get("hints") or []
    if not hints and noise:
        hints = noise.get("hints") or []
    if not hints:
        return ""
    return '<div class="hints">{}: {}</div>'.format(
        _e(_t(lang, "hints.prefix")), "; ".join(_e(h) for h in hints))


def _noise_row(candidate, *, lang="en"):
    noise = candidate.get("noise", {})
    category = noise.get("category")
    tag_text = _t(lang, "tag.blame_pointed")
    if category:
        tag_text += ", " + str(category)
    signals = noise.get("signals", [])
    signals_html = ""
    if signals:
        signals_html = '<div class="signals">{}</div>'.format(
            "; ".join(_e(s) for s in signals))
    return (
        '<div class="row noise">'
        '<span class="date">{date}</span>'
        '<span class="dot">&#9675;</span>'
        '<span class="entry">'
        '<span class="subject">{sha} {subject}</span>'
        '<span class="tag noise">{tag}</span>'
        '{signals}{hints}'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        tag=_e(tag_text),
        signals=signals_html,
        hints=_hints_html(candidate, lang=lang),
    )


def _revert_row(candidate, *, lang="en"):
    return (
        '<div class="row revert">'
        '<span class="date">{date}</span>'
        '<span class="dot">&#8635;</span>'
        '<span class="entry">'
        '<span class="subject">{sha} {subject}</span>'
        '<span class="tag noise">{tag}</span>'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        tag=_e(_t(lang, "tag.revert_chain")),
    )


def _legend_html(lang):
    """The dot legend: one short phrase per state, nothing more.

    Earlier versions of this legend also carried two nuances that belong
    elsewhere, not because they were wrong, but because a figure caption
    a reader will not read is worse than a shorter one they will:

    - "a filled dot can also carry a noise tag when the cited commit is a
      squash" -- a real row that is also noise already shows a second
      "also flagged noise" tag right on that row (see `_real_row` above);
      the row says it, so the legend does not need to.
    - "revert chains are kept regardless of noise scoring because
      reverted-then-reapplied code is the strongest do-not-delete signal
      this tool has" -- that is the *reason* for the revert-chain rule,
      not a description of the dot, and it already lives in
      strategy-tree.md's step 5 and noise-catalog.md's framing of what a
      revert means; duplicating it here would be the second copy this
      project would then have to keep in sync.
    """
    return (
        '<ul class="legend">'
        '<li><span class="ldot real">&#9679;</span> {real}</li>'
        '<li><span class="ldot noise">&#9675;</span> {noise}</li>'
        '<li><span class="ldot">&#9675;</span> {plain}</li>'
        '<li><span class="ldot revert">&#8635;</span> {revert}</li>'
        '</ul>'
    ).format(
        real=_e(_t(lang, "legend.real")),
        noise=_e(_t(lang, "legend.noise")),
        plain=_e(_t(lang, "legend.plain")),
        revert=_e(_t(lang, "legend.revert")),
    )


def _snippet_unavailable_label(lang, reason, **kwargs):
    """Chrome for a snippet that could not be shown, keyed by `reason`
    (trace.py's `_compute_snippet`: "missing-at-head", "out-of-range",
    "binary", "irregular-line-break"). An unrecognized reason -- most
    likely an older trace file whose `snippet.reason` predates one of
    these four, or names a reason string this key once used before a
    rename (e.g. the pre-generalization "form-feed"), or simply None --
    falls back to a generic message rather than leaking a raw key.
    """
    lang = _resolve_lang(lang)
    key = "snippet.unavailable." + str(reason)
    template = (_STRINGS[lang].get(key) or _STRINGS["en"].get(key)
                or _STRINGS[lang]["snippet.unavailable.generic"])
    return template.format(**kwargs) if kwargs else template


def _snippet_html(trace_data, lang):
    """The target lines plus a few of context, directly under the verdict
    block, so a reader can see what is being judged without opening an
    editor. Reads only `trace_data["snippet"]` (trace.py's
    `_compute_snippet`); an older trace file that predates this key simply
    has no such entry, so this renders nothing at all rather than an empty
    box (see the module docstring's rule that every new JSON key must be
    tolerated absent).

    Every line of source is user data straight from the repository under
    trace, so it goes through `_e` exactly like a commit subject or
    author name -- this is the single riskiest injection surface the page
    has, since unlike a subject line it can be arbitrarily long and
    contain arbitrary markup by construction (see test_render_snippet.py's
    `</pre><script>` case).
    """
    snippet = trace_data.get("snippet")
    if not isinstance(snippet, dict):
        return ""
    header = _e(_t(lang, "card.snippet"))
    if not snippet.get("available"):
        target = trace_data.get("target", {})
        text = _e(_snippet_unavailable_label(
            lang, snippet.get("reason"),
            start=target.get("start", "?"), end=target.get("end", "?"),
        ))
        return (
            '<div class="card snippet-card"><strong>{header}</strong>'
            '<p class="snippet-unavailable">{text}</p></div>'
        ).format(header=header, text=text)

    lines = snippet.get("lines") or []
    start_line = snippet.get("start_line", 1)
    target_start = snippet.get("target_start")
    target_end = snippet.get("target_end")
    rows = []
    for offset, line in enumerate(lines):
        try:
            num = int(start_line) + offset
        except (TypeError, ValueError):
            num = offset
        in_target = (isinstance(target_start, int) and isinstance(target_end, int)
                     and target_start <= num <= target_end)
        rows.append(
            '<div class="snippet-row{cls}">'
            '<span class="snippet-num">{num}</span>'
            '<span class="snippet-code">{code}</span>'
            '</div>'.format(
                cls=" target" if in_target else "",
                num=num,
                code=_e(line),
            )
        )
    return (
        '<div class="card snippet-card"><strong>{header}</strong>'
        '<div class="snippet">{rows}</div></div>'
    ).format(header=header, rows="".join(rows))


def _activity_html(trace_data, lang):
    """Recency and ownership facts for the History card: when the target
    lines (or, failing that, the file) were last touched, how many commits
    touched the file in the last year, and its main authors. Reads only
    `trace_data["activity"]` (trace.py's `_compute_activity`); absent
    entirely (older trace file) or with every fact degraded to None/[]
    both render nothing, same reasoning as `_snippet_html`.
    """
    activity = trace_data.get("activity")
    if not isinstance(activity, dict):
        return ""
    items = []

    last_touch = activity.get("last_touch")
    if isinstance(last_touch, dict) and last_touch.get("date"):
        scope = last_touch.get("scope")
        key = "activity.last_touch.lines" if scope == "lines" else "activity.last_touch.file"
        items.append("<li>{}</li>".format(_t(
            lang, key,
            date=_day(last_touch.get("date")),
            sha=_short(last_touch.get("sha", "")),
        )))

    commits_last_year = activity.get("commits_last_year")
    if isinstance(commits_last_year, int) and not isinstance(commits_last_year, bool):
        items.append("<li>{}</li>".format(_t(
            lang, "activity.commits_last_year", count=commits_last_year)))

    top_authors = activity.get("top_authors")
    if isinstance(top_authors, list):
        names = ", ".join(
            "{} ({})".format(_e(a.get("name", "")), int(a.get("count") or 0))
            for a in top_authors if isinstance(a, dict) and a.get("name")
        )
        if names:
            items.append("<li>{}</li>".format(_t(lang, "activity.top_authors", names=names)))

    if not items:
        return ""
    return '<ul class="activity">{}</ul>'.format("".join(items))


def _cmd_line(repo, args):
    """One reproduction command, as a copy-pasteable single line: `git -C
    <repo> <args...>`, every token shell-quoted. `-C` (rather than a `cd`
    prefix) so the line runs unmodified from any directory.
    """
    tokens = ["git", "-C", str(repo)] + [str(a) for a in args]
    return " ".join(shlex.quote(t) for t in tokens)


def _repro_html(trace_data, verdict_data, lang):
    """A collapsed `<details>` at the very bottom of the page listing the
    actual git commands this trace ran, plus `git show` for whichever
    commit(s) the verdict cites as real. Built entirely from
    `trace_data["commands"]` (trace.py's own recorded argv, see trace()'s
    docstring for `commands`) and `trace_data["repo"]`, so every line here
    is a command that this trace actually issued, not an idealized
    rewrite -- a command trace.py chose not to run (an empty needle list,
    a failed line-history search) simply has no entry in `commands` and so
    never appears here either.

    Absent `trace_data["repo"]` or `trace_data["commands"]` (an older
    trace file that predates this feature) renders nothing, same
    reasoning as `_snippet_html`/`_activity_html`.
    """
    repo = trace_data.get("repo")
    commands = trace_data.get("commands")
    if not repo or not isinstance(commands, list):
        return ""

    lines = [
        _cmd_line(repo, c["args"]) for c in commands
        if isinstance(c, dict) and c.get("args")
    ]

    # real_introduction_refs, not commit_refs: a `superseded`/`reference`/
    # etc-tagged citation is not the commit this section's `git show`
    # entries are meant to reproduce (see citation.py's module docstring).
    commit_refs = citation.real_introduction_refs(verdict_data.get("evidence"))
    real_shas = citation.real_shas(trace_data, commit_refs)
    for sha in sorted(real_shas):
        lines.append(_cmd_line(repo, ["show", sha]))

    if not lines:
        return ""
    return (
        '<details class="repro">'
        '<summary>{summary}</summary>'
        '<button type="button" data-copy="repro-cmds">{copy_label}</button>'
        '<pre id="repro-cmds">{text}</pre>'
        '</details>'
    ).format(
        summary=_e(_t(lang, "card.repro")),
        copy_label=_e(_t(lang, "button.copy")),
        text=_e("\n".join(lines)),
    )


def _arc_html(evidence_items, lang):
    """The reason's lifetime: what the code was introduced for, and, when
    the verdict says so, what retired that reason. Reads only evidence
    items tagged `role: "introduced"` or `role: "superseded"`
    (verdict.py's `EVIDENCE_ROLES`); every other evidence item, tagged with
    a different role or with none at all, still only ever renders in the
    plain Evidence list further down the page. Neither role present (every
    verdict written before roles existed, or one with no lifecycle story
    to tell) renders nothing here at all -- this block is the argument for
    a grade, not a fact about the code, so it must not appear when nobody
    made that argument.

    Order follows the evidence list as written, not a fixed
    introduced-then-superseded order, so an agent that lists more than one
    step of either kind (rare, but not forbidden by the schema) still
    reads left to right the way it was written.
    """
    steps = [e for e in evidence_items if e.get("role") in ("introduced", "superseded")]
    if not steps:
        return ""
    parts = []
    for e in steps:
        role_label = _e(_t(lang, "role." + str(e.get("role"))))
        ref = _e(e.get("ref", ""))
        note = e.get("note")
        note_html = " {}".format(_e(note)) if note else ""
        parts.append(
            '<span class="arc-step"><span class="tag role">{role}</span> '
            '<code>{ref}</code>{note}</span>'.format(role=role_label, ref=ref, note=note_html)
        )
    arrow = '<span class="arc-arrow">&#8594;</span>'
    return (
        '<div class="section arc-section"><strong>{header}</strong>'
        '<div class="arc">{steps}</div></div>'
    ).format(header=_e(_t(lang, "card.lifecycle")), steps=arrow.join(parts))


def _role_tally(evidence_items, role):
    """(total, present) for every evidence item tagged with `role`.

    `present` is item existence: at least one evidence item carries this
    role at all, regardless of what it counts to. `total` is what to
    display: each matching item contributes its own `count` field when
    that field is an int (an agent that searched and confirmed zero
    guarding tests can write that as one evidence item, `role: "guard",
    "count": 0`, rather than needing zero items to say so), or 1 when the
    item carries no such field (the common case: one evidence item is one
    guard, or one reference, and nothing more needs saying). The two are
    returned separately because `present` decides whether the isolation
    block renders at all, while `total` decides what number appears in it
    -- an explicit zero must still render as a rendered block, not as the
    same "nobody checked" absence a `present=False` role produces.
    """
    total = 0
    present = False
    for e in evidence_items:
        if e.get("role") != role:
            continue
        present = True
        count = e.get("count")
        total += count if isinstance(count, int) and not isinstance(count, bool) else 1
    return total, present


def _isolation_html(evidence_items, lang):
    """Isolation figures: how many `guard`-role and `reference`-role
    evidence items the verdict carries, as two small numbers rather than a
    sentence a reader has to parse for them. Renders only when at least
    one of the two roles is actually present anywhere in the evidence --
    "nobody checked" and "checked, found none" are different facts, and an
    isolation block with no role-tagged evidence behind it would render
    the first as if it were the second. Once either role is present,
    though, the other side's count of zero is exactly the fact that
    matters (a `safe` verdict resting in part on "no test guards this")
    and renders as 0, not as an omitted figure.
    """
    guard_count, guard_present = _role_tally(evidence_items, "guard")
    reference_count, reference_present = _role_tally(evidence_items, "reference")
    if not guard_present and not reference_present:
        return ""
    return (
        '<div class="section"><strong>{header}</strong>'
        '<div class="stats">'
        '<div class="stat"><span class="stat-num">{guard_count}</span>'
        '<span class="stat-label">{guard_label}</span></div>'
        '<div class="stat"><span class="stat-num">{reference_count}</span>'
        '<span class="stat-label">{reference_label}</span></div>'
        '</div></div>'
    ).format(
        header=_e(_t(lang, "card.isolation")),
        guard_count=guard_count,
        reference_count=reference_count,
        guard_label=_e(_t(lang, "isolation.guard_label",
                           plural="" if guard_count == 1 else "s")),
        reference_label=_e(_t(lang, "isolation.reference_label",
                               plural="" if reference_count == 1 else "s")),
    )


def _risk_html(evidence_items, lang):
    """Residual-risk evidence (`role: "risk"`) gets its own block, placed
    near the verdict rather than at the bottom of the page, using the same
    `--warn-fg`/`--warn-bg` pair the truncation and candidate-cap
    disclosures already use (see `.warn` in `_CSS`) rather than inventing a
    new colour. A `safe` verdict that still carries a risk is exactly the
    case this exists for: the hazard must not be easier to miss than the
    grade badge above it.
    """
    items = [e for e in evidence_items if e.get("role") == "risk"]
    if not items:
        return ""
    lis = "".join(
        "<li><code>{ref}</code>{note}</li>".format(
            ref=_e(e.get("ref", "")),
            note=" {}".format(_e(e.get("note"))) if e.get("note") else "",
        )
        for e in items
    )
    return '<div class="risk"><strong>{header}</strong><ul>{items}</ul></div>'.format(
        header=_e(_t(lang, "card.risk")), items=lis)


def render(trace_data, verdict_data, *, lang="en"):
    lang = _resolve_lang(lang)
    grade = verdict_data.get("grade", "unknown")
    hue = _GRADE_HUES.get(grade, _GRADE_HUES["unknown"])
    # These four custom properties are the one place the active grade's hue
    # enters the page: every rule in _CSS that needs it reads
    # var(--grade-fg)/var(--grade-wash), and body's own rule in _CSS derives
    # those two from whichever of these four is active for the current
    # colour scheme (see the dark media query right under it). They live on
    # <body>, not <html>/:root, for two reasons: the test suite pins the
    # exact byte contents of the <html lang="..."> tag, so no attribute can
    # be added to that tag at all; and a custom property's var() reference
    # resolves against the *same element's* own cascaded values, not
    # lazily against whatever a descendant defines later -- so the derived
    # --grade-fg/--grade-wash rule has to live on this exact element, not
    # on an ancestor selector like :root, or the reference never resolves.
    root_style = (
        "--grade-fg-light:{fg_light};--grade-wash-light:{wash_light};"
        "--grade-fg-dark:{fg_dark};--grade-wash-dark:{wash_dark};"
    ).format(**hue)
    badge_key = "badge." + grade if ("badge." + grade) in _STRINGS[lang] else "badge.unknown"
    label = _t(lang, badge_key)
    target = trace_data.get("target", {})
    limits = trace_data.get("limits", {})
    evidence_items = verdict_data.get("evidence") or []

    # Three role-driven blocks, all optional, all near the verdict rather
    # than buried lower on the page or in prose (see _arc_html/_isolation_
    # html/_risk_html's own docstrings for why each one renders, or does
    # not, the way it does).
    arc_block = _arc_html(evidence_items, lang)
    risk_block = _risk_html(evidence_items, lang)
    isolation_block = _isolation_html(evidence_items, lang)

    # Which shas the verdict actually cites as the real introduction. This,
    # not list position and not "found via blame", is what decides the bold
    # tag below: trace.py sorts introduction_candidates chronologically, and
    # chronological order is not "which one is real" (see M2 in the final
    # fix report). Only the agent's own verdict knows that. citation.py
    # searches both introduction_candidates and blame_candidates, because a
    # cited commit is not guaranteed to be in the first list at all -- see
    # this module's docstring and citation.py's for the case where it
    # is not.
    #
    # real_introduction_refs, not commit_refs: an evidence item tagged
    # `role: "superseded"`/`"reference"`/`"guard"`/`"risk"` is cited
    # evidence (it still appears in the Evidence list below, and in the
    # arc/isolation/risk blocks above when its role calls for that), but it
    # is not the real introduction, and must not get this bold tag. Only
    # `role: "introduced"` or no role at all qualifies -- see citation.py's
    # module docstring for the rule.
    commit_refs = citation.real_introduction_refs(verdict_data.get("evidence"))
    real_shas = citation.real_shas(trace_data, commit_refs)
    blame_by_sha = {b.get("sha"): b for b in trace_data.get("blame_candidates", [])}

    # Order matters for the argument: the real introducing commit(s) lead
    # the timeline, then whatever blame actually pointed at, then any revert
    # chain. This is not chronological; it is rhetorical.
    #
    # `rendered` tracks every sha that has already produced a row so no
    # commit is ever shown twice. This matters beyond the noise-vs-real
    # collision this fix targets: trace.py's own `add()` puts a
    # non-noise blame result into introduction_candidates AND leaves it in
    # blame_candidates, and a cited commit can also be part of
    # revert_chain (build_f5's reintro commit is exactly this -- its
    # subject contains "reapply"). Without this guard the same row would
    # repeat under a second, and sometimes a third, tag.
    #
    # Each row is tagged `always` so the History section below can decide
    # what stays visible outside a collapsed <details> and what is folded
    # into "other candidates": the verdict's cited real commit(s), every
    # blame_candidates entry (that is what plain `git blame` pointed at,
    # the reader needs to see it whether it turned out real, noise, or
    # neither), and the revert chain are always shown; everything else
    # (pickaxe/line-history hits that are neither cited nor part of blame's
    # own output) is what gets collapsed when the timeline is long.
    revert_shas = {r.get("sha") for r in trace_data.get("revert_chain", [])}
    rows = []
    rendered = set()
    for c in trace_data.get("introduction_candidates", []):
        sha = c.get("sha")
        rendered.add(sha)
        # why == "cited": trace.py's --include-commit put this candidate here
        # because an agent explicitly named it, most often a commit none of
        # blame/pickaxe/line-history surfaced on their own. That is exactly
        # the kind of row a reader must not have to expand a collapsed
        # <details> to find, so it stays always-visible on its own, the same
        # as a blame_candidates entry, whether or not the verdict went on to
        # cite it as the real introduction.
        always = (sha in real_shas or sha in blame_by_sha or sha in revert_shas
                  or c.get("why") == "cited")
        if sha in real_shas:
            row_html = _real_row(c, noise=blame_by_sha.get(sha, {}).get("noise"), lang=lang)
        else:
            row_html = _plain_row(c, show_why=True, lang=lang)
        rows.append((always, row_html))
    for b in trace_data.get("blame_candidates", []):
        sha = b.get("sha")
        if sha in rendered:
            continue
        rendered.add(sha)
        if sha in real_shas:
            row_html = _real_row(b, noise=b.get("noise"), lang=lang)
        elif b.get("noise", {}).get("is_noise"):
            row_html = _noise_row(b, lang=lang)
        else:
            row_html = _plain_row(b, show_why=False, lang=lang)
        rows.append((True, row_html))  # every blame_candidates row is always visible
    for r in trace_data.get("revert_chain", []):
        sha = r.get("sha")
        if sha in rendered:
            continue
        rendered.add(sha)
        rows.append((True, _revert_row(r, lang=lang)))  # revert chain is always visible

    always_rows = [h for always, h in rows if always]
    other_rows = [h for always, h in rows if not always]
    if len(rows) > _HISTORY_COLLAPSE_THRESHOLD and other_rows:
        other_count = len(other_rows)
        rows_html = "".join(always_rows) + (
            '<details class="history-more">'
            '<summary>{summary}</summary>'
            '<div class="timeline">{other}</div>'
            '</details>'
        ).format(
            summary=_e(_t(lang, "history.collapse_summary", count=other_count,
                           plural="" if other_count == 1 else "s")),
            other="".join(other_rows),
        )
    else:
        rows_html = "".join(h for _, h in rows)

    # co_changed is the strongest deterministic signal the strategy tree
    # has for commit intent: what else was touched alongside the introducing
    # commit (usually a test). artifacts.py leans on this in prose; render
    # it here too so the page and the artifact cannot silently disagree
    # about what test coverage exists. trace.py now records co_changed
    # across every introduction candidate (each entry tagged with the sha
    # it came from), because the tracer itself cannot tell which one is
    # real; only show the entries whose sha is the one this page just
    # labeled real. Rendered only when non-empty so an empty list does not
    # read as "no coverage" noise.
    #
    # trace.py's CO_CHANGED_PER_COMMIT cap means the entries here can be
    # fewer than the commit actually touched; co_changed_totals carries the
    # true per-commit count so that cut is disclosed rather than left to
    # look like a complete list (see this project's rule 3). Old trace
    # JSON, from before that field existed, has no co_changed_totals key at
    # all, so its absence -- or a value of the wrong shape -- must fall
    # back to the plain sentence, never crash. And a commit that was never
    # capped (its total equals what is shown) must render that same plain
    # sentence too: disclosing a cut that did not happen would make a
    # complete list look partial, the mirror image of the problem this cap
    # exists to fix.
    co_changed_totals = trace_data.get("co_changed_totals")
    if not isinstance(co_changed_totals, dict):
        co_changed_totals = {}
    co_changed_html = ""
    co_changed = [item for item in trace_data.get("co_changed", [])
                  if item.get("sha") in real_shas]
    if co_changed:
        co_changed_paths = ", ".join(
            "<code>{}</code>".format(_e(item.get("path", "")))
            for item in co_changed
        )
        shown_by_sha = {}
        for item in co_changed:
            sha = item.get("sha")
            shown_by_sha[sha] = shown_by_sha.get(sha, 0) + 1
        total_shown = len(co_changed)
        total_true = 0
        totals_known = True
        for sha in shown_by_sha:
            total = co_changed_totals.get(sha)
            # bool is an int subclass in Python, so isinstance(True, int) is
            # True; without the extra bool check a {sha: True} total (never
            # written by trace.py, but not impossible in a hand-edited or
            # third-party trace) would be silently read as a path count of
            # 1, hiding a real cut. patch.py's _int_or_none rejects bools
            # for the same reason; see that function's own comment.
            if not isinstance(total, int) or isinstance(total, bool):
                totals_known = False
                break
            total_true += total
        if totals_known and total_true > total_shown:
            co_changed_html = '<p class="hint">{}</p>'.format(_t(
                lang, "hint.co_changed_capped",
                shown=total_shown, total=total_true, paths=co_changed_paths))
        else:
            co_changed_html = '<p class="hint">{}</p>'.format(
                _t(lang, "hint.co_changed", paths=co_changed_paths))

    evidence = "".join(
        "<li><code>{type}</code> <code>{ref}</code>{note}</li>".format(
            type=_e(e.get("type", "")),
            ref=_e(e.get("ref", "")),
            note=" ({})".format(_e(e.get("note"))) if e.get("note") else "",
        )
        for e in evidence_items
    )

    # A `conditional` verdict's conditions are things to verify before
    # deleting, not prose to skim, so they render as a checklist (a ballot
    # box glyph per item via CSS) rather than a plain bulleted list.
    conditions = verdict_data.get("conditions", [])
    conditions_block = ""
    if conditions:
        conditions_block = (
            '<div class="card"><strong>{header}</strong>'
            '<ul class="checklist">{items}</ul></div>'.format(
                header=_e(_t(lang, "card.conditions")),
                items="".join("<li>{}</li>".format(_e(c)) for c in conditions),
            )
        )

    none_text = _e(_t(lang, "chrome.none"))
    notes = trace_data.get("notes", [])
    notes_html = "".join("<li>{}</li>".format(_e(n)) for n in notes) or \
        "<li>{}</li>".format(none_text)

    warnings = []
    if limits.get("truncated"):
        warnings.append(
            '<p class="warn">{}</p>'.format(_t(
                lang, "warn.truncated",
                max_commits=_e(limits.get("max_commits", "?")),
                since=_e(limits.get("since", "?")),
            ))
        )
    if limits.get("candidate_cap_reached"):
        warnings.append(
            '<p class="warn">{}</p>'.format(_t(
                lang, "warn.candidate_cap",
                max_candidates=_e(limits.get("max_candidates", "?")),
            ))
        )
    warnings_html = "".join(warnings)

    artifact = verdict_data.get("artifact", {})

    path = target.get("path", "")
    start = target.get("start", "")
    end = target.get("end", "")
    line_range = "{}".format(_e(start)) if start == end else "{}-{}".format(_e(start), _e(end))
    path_html = _e(path)
    line_suffix = _t(lang, "chrome.line_suffix", line_range=line_range)
    title_line = "{} {}".format(path_html, line_suffix)
    h1_line = "<span class=\"path\">{}</span> {}".format(path_html, line_suffix)

    return (
        "<!doctype html>\n"
        "<html lang=\"{lang}\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>can-i-delete-this: {title_line}</title>\n"
        "<style>{css}</style>\n"
        "</head>\n"
        "<body style=\"{root_style}\">\n"
        "<main>\n"
        "<h1>{h1_line}</h1>\n"
        "<div class=\"verdict\">\n"
        "<div class=\"badge\">{label}</div>\n"
        "<p class=\"sub\">{summary}</p>\n"
        "</div>\n"
        "{arc_block}"
        "{risk_block}"
        "{isolation_block}"
        "{snippet_block}\n"
        "{conditions_block}\n"
        "<div class=\"section\"><strong>{evidence_header}</strong><ul>{evidence}</ul></div>\n"
        "<div class=\"card card-next\">\n"
        "<button type=\"button\" data-copy=\"artifact\">{copy_label}</button>\n"
        "<strong>{next_step_header}</strong>\n"
        "<pre id=\"artifact\">{artifact}</pre>\n"
        "</div>\n"
        "<div class=\"section\">\n"
        "<strong>{history_header}</strong>\n"
        "{activity_block}"
        "<div class=\"timeline\">{rows}</div>\n"
        "{legend}\n"
        "{co_changed}"
        "</div>\n"
        "<div class=\"section section-notes\">\n"
        "<strong>{notes_header}</strong>\n"
        "<ul>{notes}</ul>\n"
        "{warnings}\n"
        "</div>\n"
        "{repro_block}\n"
        "</main>\n"
        "<script>{js}</script>\n"
        "</body>\n"
        "</html>\n"
    ).format(
        lang=lang,
        title_line=title_line,
        h1_line=h1_line,
        css=_CSS,
        js=_JS_TEMPLATE.format(copied=_t(lang, "button.copied")),
        summary=_e(verdict_data.get("summary", "")),
        root_style=root_style,
        label=_e(label),
        arc_block=arc_block,
        risk_block=risk_block,
        isolation_block=isolation_block,
        snippet_block=_snippet_html(trace_data, lang),
        evidence_header=_e(_t(lang, "card.evidence")),
        copy_label=_e(_t(lang, "button.copy")),
        next_step_header=_t(lang, "card.next_step", kind=_e(artifact.get("kind", ""))),
        history_header=_e(_t(lang, "card.history")),
        activity_block=_activity_html(trace_data, lang),
        rows=rows_html or "<p>{}</p>".format(_e(_t(lang, "chrome.no_history"))),
        legend=_legend_html(lang),
        co_changed=co_changed_html,
        evidence=evidence or "<li>{}</li>".format(none_text),
        conditions_block=conditions_block,
        artifact=_e(artifact.get("content", "")),
        notes_header=_e(_t(lang, "card.notes")),
        notes=notes_html,
        warnings=warnings_html,
        repro_block=_repro_html(trace_data, verdict_data, lang),
    )


# History rows at or below this count render flat, exactly as before this
# collapsing feature existed (the fixtures and small repos this project is
# tested against). Above it, rows the verdict does not cite as real, that
# blame did not point at, and that are not part of a revert chain fold into
# a collapsed <details> so the reader is not asked to skim hundreds of
# dates before reaching the badge's answer.
_HISTORY_COLLAPSE_THRESHOLD = 12


def write_report(trace_data, verdict_data, *, outdir=None, lang="en"):
    """Write the rendered report to a file and return its path.

    Never writes into the user's repository: defaults to the system temp
    directory, and callers may only redirect to another explicit outdir.
    """
    target = trace_data.get("target", {})
    stem = os.path.basename(str(target.get("path", "report"))).replace(".", "_")
    name = "cidt-{}-{}.html".format(stem, target.get("start", 0))
    path = os.path.join(outdir or tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(trace_data, verdict_data, lang=lang))
    return path


def main():
    ap = argparse.ArgumentParser(description="Render a can-i-delete-this report.")
    ap.add_argument("--trace", required=True, help="path to trace.json (trace.py's output)")
    ap.add_argument("--verdict", required=True, help="path to verdict.json (the verdict you wrote and validated)")
    ap.add_argument("--outdir", default=None, help="directory to write the report into "
                    "(defaults to the system temp directory)")
    ap.add_argument("--lang", default="en", help="language for the report's own text "
                    "(en, ko; unknown values fall back to en). Data read from git or "
                    "the verdict -- shas, paths, subjects, authors, dates -- is never "
                    "translated.")
    args = ap.parse_args()
    with open(args.trace, encoding="utf-8") as fh:
        trace_data = json.load(fh)
    with open(args.verdict, encoding="utf-8") as fh:
        verdict_data = json.load(fh)
    print(write_report(trace_data, verdict_data, outdir=args.outdir, lang=args.lang))


if __name__ == "__main__":
    main()
