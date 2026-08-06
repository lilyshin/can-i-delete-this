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
"""

import argparse
import html
import json
import os
import tempfile

import citation

_BADGE = {
    "danger": ("Do not delete", "#b42318", "#fee4e2"),
    "conditional": ("Delete only if", "#b54708", "#fef0c7"),
    "safe": ("Safe to delete", "#027a48", "#d1fadf"),
    "unknown": ("Inconclusive", "#475467", "#eaecf0"),
}

_WHY_LABEL = {
    "blame": "found via blame",
    "pickaxe": "found via pickaxe (blame missed it)",
    "line-history": "found via line history",
    "follow": "found via rename-follow",
}

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
.warn { color:var(--danger); background:var(--danger-bg); border-radius:8px;
        padding:.6rem .85rem; margin:.7rem 0 0; font-size:.9rem; }
.warn:first-child { margin-top:0; }
.hint { color:var(--muted); font-size:.85rem; margin:.4rem 0 0; }
code { background:var(--code); border-radius:4px; padding:.05rem .3rem;
       word-break:break-word; }
"""

_JS = """
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-copy]');
  if (!b) return;
  var text = document.getElementById(b.getAttribute('data-copy')).textContent;
  var done = function () {
    var old = b.textContent; b.textContent = 'Copied';
    setTimeout(function () { b.textContent = old; }, 1200);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, function () {});
  }
});
"""


def _e(value):
    """Escape any value for safe embedding in HTML text or attributes."""
    return html.escape(str(value), quote=True)


def _day(iso):
    return _e(str(iso)[:10])


def _short(sha):
    return _e(str(sha)[:7])


def _real_row(candidate, *, noise=None):
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
    why_label = _WHY_LABEL.get(why, why)
    author = _e(candidate.get("author", ""))
    email = candidate.get("author_email")
    who = "{} &lt;{}&gt;".format(author, _e(email)) if email else author

    noise_html = ""
    if noise and noise.get("is_noise"):
        tag_text = "also flagged noise"
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
        '<span class="tag real">real introduction</span>'
        '{noise}'
        '<div class="meta">{who} &middot; {why}</div>'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        noise=noise_html,
        who=who,
        why=_e(why_label),
    )


def _plain_row(candidate, *, show_why=False):
    """A candidate that is neither the verdict's cited real introduction
    nor scored as noise: found along the way, cited by nothing.
    """
    why = candidate.get("why", "")
    why_label = _WHY_LABEL.get(why, why)
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


def _noise_row(candidate):
    noise = candidate.get("noise", {})
    category = noise.get("category")
    tag_text = "blame pointed here"
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


def _revert_row(candidate):
    return (
        '<div class="row revert">'
        '<span class="date">{date}</span>'
        '<span class="dot">&#8635;</span>'
        '<span class="entry">'
        '<span class="subject">{sha} {subject}</span>'
        '<span class="tag noise">revert chain</span>'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
    )


def render(trace_data, verdict_data):
    grade = verdict_data.get("grade", "unknown")
    label, fg, bg = _BADGE.get(grade, _BADGE["unknown"])
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
    rows = []
    rendered = set()
    for c in trace_data.get("introduction_candidates", []):
        sha = c.get("sha")
        rendered.add(sha)
        if sha in real_shas:
            rows.append(_real_row(c, noise=blame_by_sha.get(sha, {}).get("noise")))
        else:
            rows.append(_plain_row(c, show_why=True))
    for b in trace_data.get("blame_candidates", []):
        sha = b.get("sha")
        if sha in rendered:
            continue
        rendered.add(sha)
        if sha in real_shas:
            rows.append(_real_row(b, noise=b.get("noise")))
        elif b.get("noise", {}).get("is_noise"):
            rows.append(_noise_row(b))
        else:
            rows.append(_plain_row(b, show_why=False))
    for r in trace_data.get("revert_chain", []):
        sha = r.get("sha")
        if sha in rendered:
            continue
        rendered.add(sha)
        rows.append(_revert_row(r))

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
        co_changed_html = (
            '<p class="hint">Also touched in the introducing commit: '
            "{}</p>".format(co_changed_paths)
        )

    evidence_items = verdict_data.get("evidence", [])
    evidence = "".join(
        "<li><code>{type}</code> <code>{ref}</code>{note}</li>".format(
            type=_e(e.get("type", "")),
            ref=_e(e.get("ref", "")),
            note=" ({})".format(_e(e.get("note"))) if e.get("note") else "",
        )
        for e in evidence_items
    )

    conditions = verdict_data.get("conditions", [])
    conditions_block = ""
    if conditions:
        conditions_block = (
            '<div class="card"><strong>Conditions</strong><ul>{}</ul></div>'.format(
                "".join("<li>{}</li>".format(_e(c)) for c in conditions)
            )
        )

    notes = trace_data.get("notes", [])
    notes_html = "".join("<li>{}</li>".format(_e(n)) for n in notes) or "<li>none</li>"

    warnings = []
    if limits.get("truncated"):
        warnings.append(
            '<p class="warn">History walk was truncated at {max_commits} commits '
            '(since {since}). Older introducing commits may exist but were not '
            'reached.</p>'.format(
                max_commits=_e(limits.get("max_commits", "?")),
                since=_e(limits.get("since", "?")),
            )
        )
    if limits.get("candidate_cap_reached"):
        warnings.append(
            '<p class="warn">Candidate cap of {max_candidates} was reached. '
            'This investigation stopped collecting candidates before exhausting '
            'the history; treat the result as partial, not conclusive.</p>'.format(
                max_candidates=_e(limits.get("max_candidates", "?")),
            )
        )
    warnings_html = "".join(warnings)

    artifact = verdict_data.get("artifact", {})

    path = target.get("path", "")
    start = target.get("start", "")
    end = target.get("end", "")
    line_range = "{}".format(_e(start)) if start == end else "{}-{}".format(_e(start), _e(end))

    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>can-i-delete-this: {path} line {line_range}</title>\n"
        "<style>{css}</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        "<h1><span class=\"path\">{path}</span> line {line_range}</h1>\n"
        "<p class=\"sub\">{summary}</p>\n"
        "<div class=\"badge\" style=\"color:{fg};background:{bg}\">{label}</div>\n"
        "<div class=\"card\">\n"
        "<strong>History: blame vs. the real introduction</strong>\n"
        "<div class=\"timeline\">{rows}</div>\n"
        "<p class=\"hint\">Filled dot: the commit the verdict cites as the real "
        "introduction, even when that commit is only found in the "
        "noise-flagged blame list; a noise tag on a filled-dot row means it is "
        "still the real introduction, and also a commit that would have "
        "scored as noise on its own (a squash commit is the common case, see "
        "N10). Struck-through hollow dot: a commit scored as noise and not "
        "cited by the verdict, including whatever plain <code>git blame</code> "
        "would have pointed you to. Plain hollow dot: a candidate this search "
        "found that was neither cited as real nor scored as noise. "
        "Circular-arrow dot: part of a revert/reapply chain, kept regardless "
        "of noise scoring or citation, because reverted-then-reapplied code is "
        "the strongest do-not-delete signal this tool has.</p>\n"
        "{co_changed}"
        "</div>\n"
        "<div class=\"card\"><strong>Evidence</strong><ul>{evidence}</ul></div>\n"
        "{conditions_block}\n"
        "<div class=\"card\">\n"
        "<button type=\"button\" data-copy=\"artifact\">Copy</button>\n"
        "<strong>Next step ({kind})</strong>\n"
        "<pre id=\"artifact\">{artifact}</pre>\n"
        "</div>\n"
        "<div class=\"card\">\n"
        "<strong>Notes and limits</strong>\n"
        "<ul>{notes}</ul>\n"
        "{warnings}\n"
        "</div>\n"
        "</main>\n"
        "<script>{js}</script>\n"
        "</body>\n"
        "</html>\n"
    ).format(
        path=_e(path),
        line_range=line_range,
        css=_CSS,
        js=_JS,
        summary=_e(verdict_data.get("summary", "")),
        fg=fg,
        bg=bg,
        label=_e(label),
        rows="".join(rows) or "<p>No history found.</p>",
        co_changed=co_changed_html,
        evidence=evidence or "<li>none</li>",
        conditions_block=conditions_block,
        kind=_e(artifact.get("kind", "")),
        artifact=_e(artifact.get("content", "")),
        notes=notes_html,
        warnings=warnings_html,
    )


def write_report(trace_data, verdict_data, *, outdir=None):
    """Write the rendered report to a file and return its path.

    Never writes into the user's repository: defaults to the system temp
    directory, and callers may only redirect to another explicit outdir.
    """
    target = trace_data.get("target", {})
    stem = os.path.basename(str(target.get("path", "report"))).replace(".", "_")
    name = "cidt-{}-{}.html".format(stem, target.get("start", 0))
    path = os.path.join(outdir or tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(trace_data, verdict_data))
    return path


def main():
    ap = argparse.ArgumentParser(description="Render a can-i-delete-this report.")
    ap.add_argument("--trace", required=True, help="path to trace.json (trace.py's output)")
    ap.add_argument("--verdict", required=True, help="path to verdict.json (the verdict you wrote and validated)")
    ap.add_argument("--outdir", default=None, help="directory to write the report into "
                    "(defaults to the system temp directory)")
    args = ap.parse_args()
    with open(args.trace, encoding="utf-8") as fh:
        trace_data = json.load(fh)
    with open(args.verdict, encoding="utf-8") as fh:
        verdict_data = json.load(fh)
    print(write_report(trace_data, verdict_data, outdir=args.outdir))


if __name__ == "__main__":
    main()
