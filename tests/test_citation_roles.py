"""Regression tests for the 0.6.1 evidence-role attribution fix.

0.5.0 added an optional `role` field to evidence items (verdict.py's
EVIDENCE_ROLES), but citation.py's matching -- which decides the bold
"real introduction" tag in render.py and the "// KEEP:" attribution in
artifacts.py -- never learned about it. Every cited commit, regardless of
role, was treated as the real introduction. A `role: "reference"` item (a
comment merely mentioning the code) or a `role: "superseded"` item (the
commit that retired the reason, a different fact the lifetime arc already
shows) got exactly the same bold treatment as the actual `role:
"introduced"` commit.

The rule this fix implements: a commit is the real introduction when its
evidence item has `role: "introduced"` or carries no role at all (older
verdicts, written before roles existed, must keep rendering unchanged).
Every other role -- superseded, reference, guard, risk -- is real, cited
evidence (still in the Evidence list, and in the arc/isolation/risk blocks
when its role calls for that) but never the real-introduction tag.

TestRoleFiltering uses the same hand-built TRACE-dict style as
test_render_roles.py (no git repository, since these are pure render.py
string-building checks); TestExactReproduction builds the real
build_deep_history fixture once in setUpClass and reuses the resulting
trace across its test methods, since that build costs several seconds and
the task this fixes already runs 279 tests reusing it elsewhere.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import artifacts
import citation
import render
import trace as tracer


def _parse_rows(html):
    """Every timeline row as (row_class, subject_text, tag_text).

    Each row div's own closing markup is exactly `</span></div>` (the
    `<span class="entry">...</span>` closing, then the row's own closing
    div), and that literal substring appears nowhere else inside a row
    (nested "meta"/"signals" blocks are plain divs, not spans), so the
    first occurrence of it after a row's opening tag reliably ends that
    row without spilling into the next one. The regex the existing
    `test_citation_resolution.py` helper uses
    (`<div class="row[^"]*">.*?</div></div>`) only works by coincidence
    when the matched row happens to be the very last one in the timeline
    (so the timeline wrapper's own closing div supplies the second
    `</div>`); it does not reach here, since these tests need rows in the
    middle of a multi-row timeline.
    """
    rows = []
    for part in re.split(r'(?=<div class="row)', html):
        if not part.startswith('<div class="row'):
            continue
        end = part.index("</span></div>") + len("</span></div>")
        chunk = part[:end]
        cls = re.search(r'class="row\s*([^"]*)"', chunk).group(1).strip()
        subject = re.search(r'<span class="subject">([^<]*)</span>', chunk)
        tag = re.search(r'<span class="tag[^"]*">([^<]*)</span>', chunk)
        rows.append((cls, subject.group(1) if subject else "",
                     tag.group(1) if tag else ""))
    return rows


TRACE = {
    "target": {"path": "session_guard.py", "start": 4, "end": 4},
    "blame_candidates": [],
    "introduction_candidates": [
        {"sha": "aaaaaaa" + "0" * 33, "why": "pickaxe",
         "subject": "fix: reject replayed session tokens (#5521)",
         "date": "2018-01-15T10:00:00+00:00", "author": "Kim",
         "author_email": "kim@example.com", "files_changed": 1},
        {"sha": "bbbbbbb" + "0" * 33, "why": "blame",
         "subject": "chore: apply formatter",
         "date": "2018-05-06T10:00:00+00:00", "author": "Lee",
         "author_email": "lee@example.com", "files_changed": 1},
    ],
    "revert_chain": [], "co_changed": [],
    "limits": {"max_commits": 5000, "since": "5 years ago", "truncated": False,
               "max_candidates": 200, "candidate_cap_reached": False},
    "notes": [],
}

INTRODUCED_SHA = "aaaaaaa"
CITED_ROLE_SHA = "bbbbbbb"


def _verdict(evidence, grade="danger"):
    return {
        "grade": grade,
        "summary": "Regression check for evidence-role attribution.",
        "evidence": evidence,
        "conditions": [],
        "artifact": {"kind": "keep-comment", "content": "// KEEP: placeholder"},
    }


class TestRoleFiltering(unittest.TestCase):
    """Pure render.py checks against a hand-built trace: no git involved,
    so these are cheap regardless of how many role combinations they
    cover.
    """

    def test_introduced_and_reference_only_introduced_is_real(self):
        """The exact reproduction from the bug report, in miniature: an
        `introduced` commit and a `reference` commit both cited. Only the
        `introduced` one may carry the real-introduction tag.
        """
        evidence = [
            {"type": "commit", "ref": INTRODUCED_SHA, "role": "introduced",
             "note": "the real fix"},
            {"type": "commit", "ref": CITED_ROLE_SHA, "role": "reference",
             "note": "the formatter commit blame reports"},
        ]
        html = render.render(TRACE, _verdict(evidence))
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 1, "expected exactly one real row, got {}".format(rows))
        self.assertIn(INTRODUCED_SHA, real_rows[0][1])
        self.assertEqual(real_rows[0][2], "real introduction")
        # The reference commit must still appear (it is cited evidence),
        # just not tagged real.
        cited_rows = [r for r in rows if CITED_ROLE_SHA in r[1]]
        self.assertEqual(len(cited_rows), 1)
        self.assertNotEqual(cited_rows[0][0], "real")

    def test_superseded_role_does_not_get_real_tag(self):
        evidence = [
            {"type": "commit", "ref": INTRODUCED_SHA, "role": "introduced", "note": "added it"},
            {"type": "commit", "ref": CITED_ROLE_SHA, "role": "superseded", "note": "retired it"},
        ]
        html = render.render(TRACE, _verdict(evidence))
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 1)
        self.assertIn(INTRODUCED_SHA, real_rows[0][1])

    def test_risk_role_does_not_get_real_tag(self):
        evidence = [
            {"type": "commit", "ref": INTRODUCED_SHA, "role": "introduced", "note": "added it"},
            {"type": "commit", "ref": CITED_ROLE_SHA, "role": "risk", "note": "still a hazard"},
        ]
        html = render.render(TRACE, _verdict(evidence))
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 1)
        self.assertIn(INTRODUCED_SHA, real_rows[0][1])

    def test_no_role_at_all_still_gets_real_tag(self):
        """A verdict written before roles existed (or by a caller that
        still omits the field) must keep rendering exactly as it always
        did: an evidence item with no `role` key is treated the same as
        `role: "introduced"`.
        """
        evidence = [{"type": "commit", "ref": INTRODUCED_SHA, "note": "the fix"}]
        html = render.render(TRACE, _verdict(evidence))
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 1)
        self.assertIn(INTRODUCED_SHA, real_rows[0][1])

    def test_only_non_introduced_roles_cited_no_row_marked_real(self):
        evidence = [
            {"type": "commit", "ref": CITED_ROLE_SHA, "role": "reference",
             "note": "blame points here"},
        ]
        html = render.render(TRACE, _verdict(evidence))
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 0)

    def test_citation_module_filters_by_role_directly(self):
        """Pin citation.py's own contract, not just render.py's use of it."""
        evidence = [
            {"type": "commit", "ref": "aaaaaaa", "role": "introduced"},
            {"type": "commit", "ref": "bbbbbbb", "role": "reference"},
            {"type": "commit", "ref": "ccccccc", "role": "superseded"},
            {"type": "commit", "ref": "ddddddd", "role": "risk"},
            {"type": "commit", "ref": "eeeeeee"},
        ]
        self.assertEqual(citation.real_introduction_refs(evidence),
                          ["aaaaaaa", "eeeeeee"])
        # commit_refs (unfiltered) still returns every one of them, for
        # callers that need to know a citation was made at all.
        self.assertEqual(
            citation.commit_refs(evidence),
            ["aaaaaaa", "bbbbbbb", "ccccccc", "ddddddd", "eeeeeee"])


class TestExactReproduction(unittest.TestCase):
    """The bug report's exact scenario, against the real build_deep_history
    fixture (a genuine repository, real blame/pickaxe results), plus the
    artifacts.py checks the same fix must also cover. The fixture is built
    once in setUpClass and its trace reused read-only by every test
    method here; render.render()/artifacts.skeleton() don't mutate it.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_deep_history(cls.tmp.name)
        cls.trace = tracer.trace(cls.info["repo"], cls.info["path"],
                                  cls.info["line"], cls.info["line"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _evidence(self, real_role="introduced", cited_role="reference"):
        return [
            {"type": "commit", "ref": self.info["real_sha"][:7], "role": real_role,
             "note": "the real security fix"},
            {"type": "commit", "ref": self.info["noise_sha"][:7], "role": cited_role,
             "note": "the formatter commit blame reports"},
        ]

    def test_only_the_introduced_commit_is_marked_real(self):
        html = render.render(self.trace, _verdict(self._evidence()))
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 1, "expected exactly one real row, got {}".format(rows))
        self.assertIn(self.info["real_sha"][:7], real_rows[0][1])
        noise_rows = [r for r in rows if self.info["noise_sha"][:7] in r[1]]
        self.assertEqual(len(noise_rows), 1)
        self.assertNotEqual(noise_rows[0][0], "real",
                             "the formatter commit blame reports must not be marked real")

    def test_superseded_role_lifetime_arc_still_renders(self):
        """The fix must stop a role from being mislabeled, not make it
        invisible: a `superseded` citation must still drive the lifetime
        arc render.py already draws for it.
        """
        evidence = self._evidence(cited_role="superseded")
        html = render.render(self.trace, _verdict(evidence))
        self.assertIn("arc-section", html)
        self.assertIn("Superseded", html)
        self.assertIn(self.info["noise_sha"][:7], html)
        rows = _parse_rows(html)
        real_rows = [r for r in rows if r[0] == "real"]
        self.assertEqual(len(real_rows), 1)
        self.assertIn(self.info["real_sha"][:7], real_rows[0][1])

    def test_artifact_names_the_introduced_commit_even_when_reference_listed_first(self):
        evidence = [
            {"type": "commit", "ref": self.info["noise_sha"][:7], "role": "reference",
             "note": "the formatter commit blame reports"},
            {"type": "commit", "ref": self.info["real_sha"][:7], "role": "introduced",
             "note": "the real security fix"},
        ]
        out = artifacts.skeleton("danger", self.trace, evidence)
        self.assertIn(self.info["real_sha"][:7], out)
        self.assertNotIn(self.info["noise_sha"][:7], out)

    def test_artifact_degrades_honestly_when_only_non_introduced_roles_cited(self):
        """No `introduced`-or-roleless commit was cited at all here (only
        a `reference`). The artifact must not silently fall back to
        introduction_candidates[0] -- that is the exact M2 misattribution
        citation.py/_top exist to prevent -- it must say plainly that
        nothing resolves to the real introduction.
        """
        evidence = [
            {"type": "commit", "ref": self.info["noise_sha"][:7], "role": "reference",
             "note": "blame points here"},
        ]
        out = artifacts.skeleton("danger", self.trace, evidence)
        oldest = self.trace["introduction_candidates"][0]
        self.assertNotIn(oldest["sha"][:7], out,
                          "must not silently pick the oldest candidate")
        self.assertIn(self.info["noise_sha"][:7], out)
        self.assertTrue(
            "not tagged" in out.lower() or "nothing to attribute" in out.lower()
            or "not resolve" in out.lower() or "unresolved" in out.lower(),
            "artifact text must plainly say no real introduction was cited, got: {!r}".format(out))


if __name__ == "__main__":
    unittest.main()
