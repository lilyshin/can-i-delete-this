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
  category as a second tag. This is not a contradiction to hide -- it is
  exactly the situation noise-catalog.md's N10 entry describes, and the
  page should say so rather than pick one fact and drop the other. The
  same commit never gets a second, separate noise row once it has been
  rendered as real.

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
import tempfile

import citation

# Colour is a function of grade, not of language, so it is kept separate
# from the label text in _STRINGS below.
_BADGE_COLORS = {
    "danger": ("#b42318", "#fee4e2"),
    "conditional": ("#b54708", "#fef0c7"),
    "safe": ("#027a48", "#d1fadf"),
    "unknown": ("#475467", "#eaecf0"),
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
:root { color-scheme: light dark; --bg:#ffffff; --fg:#101828; --muted:#667085;
        --line:#e4e7ec; --card:#f9fafb; --code:#f2f4f7; --accent:#6941c6;
        --accent-bg:#f4ebff; --danger:#b42318; --danger-bg:#fee4e2; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0c111d; --fg:#f5f5f6; --muted:#94969c; --line:#333741;
          --card:#161b26; --code:#1f242f; --accent:#b692f6;
          --accent-bg:#2a1f3d; --danger:#fda29b; --danger-bg:#3b1512; }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin:0; padding:2.5rem 1.25rem 3rem; background:var(--bg); color:var(--fg);
       font:15px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
main { max-width: 62rem; margin: 0 auto; }
h1 { font-size:1.3rem; margin:0 0 .3rem; word-break:break-word; }
h1 .path { font-weight:400; color:var(--muted); }
.sub { color:var(--muted); margin:0 0 1.25rem; max-width:48rem; }
.badge { display:inline-block; padding:.4rem .85rem; border-radius:999px;
         font-weight:700; font-size:.85rem; letter-spacing:.01em; margin-bottom:1.5rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:1.1rem 1.35rem; margin:0 0 1.25rem; }
.card > strong { display:block; font-size:.75rem; text-transform:uppercase;
                 letter-spacing:.06em; color:var(--muted); margin-bottom:.6rem; }
.timeline { display:flex; flex-direction:column; }
.row { display:flex; gap:1rem; align-items:flex-start; padding:.7rem 0;
       border-bottom:1px dashed var(--line); overflow-x:auto; }
.row:last-child { border-bottom:0; }
.date { color:var(--muted); white-space:nowrap; min-width:6rem; padding-top:.15rem; }
.dot { min-width:1.4rem; text-align:center; padding-top:.1rem; font-weight:700; }
.entry { min-width:0; flex:1; }
.subject { word-break:break-word; }
.row.real { background:var(--accent-bg); border-radius:8px; margin:0 -0.5rem .35rem;
            padding:.8rem 0.5rem; border-bottom:none; }
.row.real .dot { color:var(--accent); }
.row.real .subject { font-weight:700; color:var(--fg); }
.row.noise .dot { color:var(--muted); }
.row.noise .subject { color:var(--muted); text-decoration:line-through;
                      text-decoration-color:var(--muted); text-decoration-thickness:1px; }
.row.revert .dot { color:var(--muted); }
.meta { color:var(--muted); font-size:.85rem; margin-top:.2rem; }
.tag { display:inline-block; font-size:.7rem; font-weight:700; text-transform:uppercase;
       letter-spacing:.03em; border-radius:4px; padding:.1rem .4rem; margin-left:.4rem;
       vertical-align:middle; }
.tag.real { background:var(--accent-bg); color:var(--accent); border:1px solid var(--accent); }
.tag.noise { background:var(--code); color:var(--muted); border:1px solid var(--line); }
.signals { color:var(--muted); font-size:.8rem; margin-top:.15rem; }
pre { background:var(--code); padding:.9rem 1rem; border-radius:8px; overflow-x:auto;
      margin:.6rem 0 0; white-space:pre-wrap; word-break:break-word; }
button { font:inherit; font-size:.85rem; cursor:pointer; border:1px solid var(--line);
         background:var(--bg); color:var(--fg); border-radius:6px;
         padding:.3rem .75rem; float:right; }
button:hover { border-color:var(--accent); }
ul { margin:.4rem 0 0; padding-left:1.2rem; }
li { margin:.15rem 0; }
ul.checklist { list-style:none; padding-left:0; }
ul.checklist li { position:relative; padding-left:1.7rem; margin:.4rem 0; }
ul.checklist li::before { content:"\2610"; position:absolute; left:0; top:0;
                          color:var(--accent); font-size:1rem; line-height:1.4; }
.warn { color:var(--danger); background:var(--danger-bg); border-radius:8px;
        padding:.6rem .85rem; margin:.7rem 0 0; font-size:.9rem; }
.warn:first-child { margin-top:0; }
.hint { color:var(--muted); font-size:.85rem; margin:.4rem 0 0; }
code { background:var(--code); border-radius:4px; padding:.05rem .3rem;
       word-break:break-word; }
ul.legend { list-style:none; padding:0; margin:.6rem 0 0; display:flex; flex-wrap:wrap;
            gap:.4rem 1.25rem; color:var(--muted); font-size:.8rem; }
ul.legend li { display:flex; align-items:center; gap:.35rem; }
ul.legend .ldot { font-weight:700; }
ul.legend .ldot.real { color:var(--accent); }
ul.legend .ldot.noise { color:var(--muted); text-decoration:line-through; }
ul.legend .ldot.revert { color:var(--muted); }
details.history-more { margin-top:.5rem; }
details.history-more > summary { cursor:pointer; color:var(--muted); font-size:.85rem;
                                  padding:.5rem .1rem; list-style:none;
                                  display:flex; align-items:center; gap:.4rem;
                                  border-radius:6px; }
details.history-more > summary::-webkit-details-marker { display:none; }
details.history-more > summary::before { content:"\25B8"; display:inline-block;
                                          font-size:.75rem; transition:transform .12s; }
details.history-more[open] > summary::before { content:"\25BE"; }
details.history-more > summary:hover { color:var(--fg); }
details.history-more > summary:focus-visible { outline:2px solid var(--accent);
                                                outline-offset:2px; }
details.history-more > .timeline { margin-top:.3rem; }
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
    exactly the N10 situation noise-catalog.md documents (a squash commit
    whose message cannot be trusted, but whose diff is). Both facts render
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
        '{noise}'
        '<div class="meta">{who} &middot; {why}</div>'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        real_tag=_e(_t(lang, "tag.real")),
        noise=noise_html,
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
        '{meta}'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        meta=meta_html,
    )


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
        '{signals}'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        tag=_e(tag_text),
        signals=signals_html,
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


def render(trace_data, verdict_data, *, lang="en"):
    lang = _resolve_lang(lang)
    grade = verdict_data.get("grade", "unknown")
    fg, bg = _BADGE_COLORS.get(grade, _BADGE_COLORS["unknown"])
    badge_key = "badge." + grade if ("badge." + grade) in _STRINGS[lang] else "badge.unknown"
    label = _t(lang, badge_key)
    target = trace_data.get("target", {})
    limits = trace_data.get("limits", {})

    # Which shas the verdict actually cites as the real introduction. This,
    # not list position and not "found via blame", is what decides the bold
    # tag below: trace.py sorts introduction_candidates chronologically, and
    # chronological order is not "which one is real" (see M2 in the final
    # fix report). Only the agent's own verdict knows that. citation.py
    # searches both introduction_candidates and blame_candidates, because a
    # cited commit is not guaranteed to be in the first list at all -- see
    # this module's docstring and citation.py's for the N10 case where it
    # is not.
    commit_refs = citation.commit_refs(verdict_data.get("evidence"))
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
    co_changed_html = ""
    co_changed = [item for item in trace_data.get("co_changed", [])
                  if item.get("sha") in real_shas]
    if co_changed:
        co_changed_paths = ", ".join(
            "<code>{}</code>".format(_e(item.get("path", "")))
            for item in co_changed
        )
        co_changed_html = '<p class="hint">{}</p>'.format(
            _t(lang, "hint.co_changed", paths=co_changed_paths))

    evidence_items = verdict_data.get("evidence", [])
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
        "<body>\n"
        "<main>\n"
        "<h1>{h1_line}</h1>\n"
        "<div class=\"badge\" style=\"color:{fg};background:{bg}\">{label}</div>\n"
        "<p class=\"sub\">{summary}</p>\n"
        "{conditions_block}\n"
        "<div class=\"card\"><strong>{evidence_header}</strong><ul>{evidence}</ul></div>\n"
        "<div class=\"card\">\n"
        "<button type=\"button\" data-copy=\"artifact\">{copy_label}</button>\n"
        "<strong>{next_step_header}</strong>\n"
        "<pre id=\"artifact\">{artifact}</pre>\n"
        "</div>\n"
        "<div class=\"card\">\n"
        "<strong>{history_header}</strong>\n"
        "<div class=\"timeline\">{rows}</div>\n"
        "{legend}\n"
        "{co_changed}"
        "</div>\n"
        "<div class=\"card\">\n"
        "<strong>{notes_header}</strong>\n"
        "<ul>{notes}</ul>\n"
        "{warnings}\n"
        "</div>\n"
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
        fg=fg,
        bg=bg,
        label=_e(label),
        evidence_header=_e(_t(lang, "card.evidence")),
        copy_label=_e(_t(lang, "button.copy")),
        next_step_header=_t(lang, "card.next_step", kind=_e(artifact.get("kind", ""))),
        history_header=_e(_t(lang, "card.history")),
        rows=rows_html or "<p>{}</p>".format(_e(_t(lang, "chrome.no_history"))),
        legend=_legend_html(lang),
        co_changed=co_changed_html,
        evidence=evidence or "<li>{}</li>".format(none_text),
        conditions_block=conditions_block,
        artifact=_e(artifact.get("content", "")),
        notes_header=_e(_t(lang, "card.notes")),
        notes=notes_html,
        warnings=warnings_html,
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
