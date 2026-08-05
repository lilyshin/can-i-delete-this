"""Render a trace plus verdict into one self-contained HTML file.

No CDN, no fonts, no libraries. The timeline is flexbox and borders so the
page renders identically offline and in both colour schemes.

The whole point of the page is to make "blame pointed at the wrong commit"
visible at a glance: noise commits from blame_candidates are rendered
greyed-out and struck through with the noise category that disqualified
them, while the real introducing commit from introduction_candidates is
rendered bold, coloured, and first. A reader should not need to read any
prose to see which commit is the answer and which one git blame lied about.
"""

import argparse
import html
import json
import os
import tempfile

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
code { background:var(--code); border-radius:4px; padding:.05rem .3rem; }
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


def _real_row(candidate):
    why = candidate.get("why", "")
    why_label = _WHY_LABEL.get(why, why)
    return (
        '<div class="row real">'
        '<span class="date">{date}</span>'
        '<span class="dot">&#9679;</span>'
        '<span class="entry">'
        '<span class="subject">{sha} {subject}</span>'
        '<span class="tag real">real introduction</span>'
        '<div class="meta">{author} &lt;{email}&gt; &middot; {why}</div>'
        '</span></div>'
    ).format(
        date=_day(candidate.get("date")),
        sha=_short(candidate.get("sha", "")),
        subject=_e(candidate.get("subject", "")),
        author=_e(candidate.get("author", "")),
        email=_e(candidate.get("author_email", "")),
        why=_e(why_label),
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

    # Order matters for the argument: the real introducing commit(s) lead
    # the timeline, then the noise commits blame actually pointed at, then
    # any revert chain. This is not chronological; it is rhetorical.
    rows = []
    for c in trace_data.get("introduction_candidates", []):
        rows.append(_real_row(c))
    for b in trace_data.get("blame_candidates", []):
        rows.append(_noise_row(b))
    for r in trace_data.get("revert_chain", []):
        rows.append(_revert_row(r))

    evidence_items = verdict_data.get("evidence", [])
    evidence = "".join(
        "<li><code>{type}</code> <code>{ref}</code>{note}</li>".format(
            type=_e(e.get("type", "")),
            ref=_e(e.get("ref", "")),
            note=" &mdash; {}".format(_e(e.get("note"))) if e.get("note") else "",
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
        "<p class=\"hint\">Filled dot: where the deletion actually originated. "
        "Struck-through hollow dot: where a plain <code>git blame</code> would "
        "have pointed you instead.</p>\n"
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
    ap.add_argument("--trace", required=True, help="path to trace.json (Task 4 output)")
    ap.add_argument("--verdict", required=True, help="path to verdict.json (Task 6 output)")
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
