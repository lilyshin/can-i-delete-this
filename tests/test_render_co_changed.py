"""Regression tests for how render() discloses trace.py's co_changed cap.

Task 1 (co_changed_totals, limits["co_changed_per_commit"]) records the true
per-commit path count alongside the (possibly capped) co_changed list, but
recording the total is useless if the report never reads it: a reader who
sees a comma-separated list of paths with no count attached has no way to
tell "this is everything" from "this is what survived a cap", and the
project's own doctrine (SKILL.md rule 3) is that a partial list not labelled
partial gets read as the whole list.

The trap this file is most worried about is the opposite direction: a commit
that was never capped (its co_changed_totals entry equals the number of
entries actually present) must render exactly the old plain sentence, with
no "N of M" language at all. A careless implementation that always prints a
count, or that triggers on `>=` instead of `>`, would make every uncapped
commit look truncated -- which is its own, quieter violation of the same
doctrine (a complete list that looks partial invites a needless
--max-co-changed re-run over nothing). That is why the uncapped test below
is written first.

Old-format trace JSON (no co_changed_totals key at all, predating Task 1)
must not crash render(): render() only ever learned of this field just now,
and a caller re-rendering an old saved trace.json is a real scenario, not a
hypothetical.
"""

import copy
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import render

_SHA = "a3f8c21" + "0" * 33

_BASE_TRACE = {
    "target": {"path": "payment.py", "start": 3, "end": 3},
    "blame_candidates": [],
    "introduction_candidates": [{
        "sha": _SHA, "why": "blame",
        "subject": "hotfix: prevent double charge (#4127)",
        "date": "2019-11-08T02:14:00+00:00", "author": "Kim",
        "author_email": "kim@example.com", "files_changed": 1,
    }],
    "revert_chain": [],
    "notes": [],
    "limits": {"max_commits": 5000, "since": "5 years ago", "truncated": False,
               "max_candidates": 200, "candidate_cap_reached": False,
               "co_changed_per_commit": 20},
}

_VERDICT = {
    "grade": "danger",
    "summary": "Guards against the #4127 double charge incident.",
    "evidence": [{"type": "commit", "ref": "a3f8c21", "note": "introduced during incident"}],
    "conditions": [],
    "artifact": {"kind": "keep-comment", "content": "// KEEP"},
}


def _hint_block(html):
    """Pull out just the co_changed <p class="hint"> paragraph.

    Isolating this from the rest of the page matters: several fixture shas
    below are padded with zeroes, so a bare substring search for a small
    integer like "2" or "7" anywhere in the whole document risks a false
    match inside a sha or a date, not the count this test actually means to
    check.
    """
    match = re.search(r'<p class="hint">(.*?)</p>', html, re.DOTALL)
    return match.group(1) if match else ""


class TestUncappedCommitIsNotDescribedAsTruncated(unittest.TestCase):
    """The trap: a commit under the cap must render the plain list, with no
    disclosure phrasing at all, in either language.

    A mutation that drops the `>` comparison (using `>=`, or omitting the
    comparison and always disclosing) turns this red: with totals equal to
    the shown count, either mutation would still print a "capped"/"of"
    phrase over a list that was never cut.
    """

    def setUp(self):
        self.trace = copy.deepcopy(_BASE_TRACE)
        self.trace["co_changed"] = [
            {"path": "payment_test.py", "sha": _SHA},
            {"path": "payment_helpers.py", "sha": _SHA},
            {"path": "payment_config.py", "sha": _SHA},
        ]
        # Exactly as many as are present: this commit was never capped.
        self.trace["co_changed_totals"] = {_SHA: 3}

    def test_english_hint_has_no_count_language(self):
        html = render.render(self.trace, _VERDICT, lang="en")
        block = _hint_block(html)
        self.assertIn("payment_test.py", block)
        self.assertNotIn("of 3", block)
        self.assertNotIn("capped", block.lower())

    def test_korean_hint_has_no_count_language(self):
        html = render.render(self.trace, _VERDICT, lang="ko")
        block = _hint_block(html)
        self.assertIn("payment_test.py", block)
        self.assertNotIn("3개", block)
        self.assertNotIn("상한", block)


class TestCappedCommitDisclosesShownAndTotal(unittest.TestCase):
    """A cited commit whose total exceeds what trace.py kept must say so,
    in both languages, with both numbers.
    """

    def setUp(self):
        self.trace = copy.deepcopy(_BASE_TRACE)
        self.trace["co_changed"] = [
            {"path": "payment_test.py", "sha": _SHA},
            {"path": "payment_helpers.py", "sha": _SHA},
        ]
        # Only 2 of the true 7 paths this commit touched survived the cap.
        self.trace["co_changed_totals"] = {_SHA: 7}

    def test_english_hint_names_both_counts(self):
        # Pinned as an ordered phrase, not two order-free digit checks: the
        # latter passes just as well when `shown` and `total` are swapped
        # (rendering the nonsensical "7 of 2 shown"), which is exactly the
        # mutation this test exists to catch. See render.py's hint.co_changed_capped.
        html = render.render(self.trace, _VERDICT, lang="en")
        block = _hint_block(html)
        self.assertIn("2 of 7", block)
        self.assertIn("payment_test.py", block)

    def test_korean_hint_names_both_counts(self):
        # Same ordering pin as the English test above, against the ko
        # template's "total 개 중 shown 개" phrasing (see hint.co_changed_capped).
        html = render.render(self.trace, _VERDICT, lang="ko")
        block = _hint_block(html)
        self.assertIn("총 7개 중 2개만 표시", block)
        self.assertIn("payment_test.py", block)

    def test_multiple_cited_commits_aggregate_shown_and_total(self):
        # co_changed is one flat, cross-commit list (the paths from two
        # cited commits are already joined into the same comma-separated
        # sentence with no per-commit label), so the shown/total count
        # follows the same flat shape: a second cited commit's own 1-shown-
        # of-1-true entry adds into the running totals rather than
        # producing a second, separate disclosure.
        other_sha = "b7d2e90" + "0" * 33
        self.trace["introduction_candidates"].append({
            "sha": other_sha, "why": "blame",
            "subject": "fix: unrelated cleanup",
            "date": "2020-01-01T00:00:00+00:00", "author": "Han",
            "author_email": "han@example.com", "files_changed": 1,
        })
        self.trace["co_changed"].append({"path": "cleanup_test.py", "sha": other_sha})
        self.trace["co_changed_totals"][other_sha] = 1
        verdict = dict(_VERDICT)
        verdict["evidence"] = [
            {"type": "commit", "ref": "a3f8c21", "note": "introduced during incident"},
            {"type": "commit", "ref": "b7d2e90", "note": "also introduced"},
        ]
        html = render.render(self.trace, verdict, lang="en")
        block = _hint_block(html)
        # shown: 2 (a3f8c21) + 1 (b7d2e90) = 3; total: 7 (a3f8c21) + 1 (b7d2e90) = 8.
        # Pinned as the ordered phrase "3 of 8", not two order-free digit
        # checks, for the same reason as test_english_hint_names_both_counts
        # above.
        self.assertIn("3 of 8", block)


class TestMissingTotalsFallsBackToPlainList(unittest.TestCase):
    """Old-format trace JSON, predating Task 1, has no co_changed_totals key
    at all. render() must not crash and must fall back to the pre-cap
    behaviour: the plain list, no count language.

    A mutation that reads `trace_data["co_changed_totals"]` without `.get`
    (or without the isinstance guard) turns this red with a KeyError or a
    TypeError instead of a rendered page.
    """

    def setUp(self):
        self.trace = copy.deepcopy(_BASE_TRACE)
        self.trace["co_changed"] = [{"path": "payment_test.py", "sha": _SHA}]
        # No co_changed_totals key at all -- the pre-Task-1 shape.

    def test_renders_without_crashing(self):
        html = render.render(self.trace, _VERDICT, lang="en")
        block = _hint_block(html)
        self.assertIn("payment_test.py", block)

    def test_no_count_language_appears(self):
        html = render.render(self.trace, _VERDICT, lang="en")
        block = _hint_block(html)
        self.assertNotIn("capped", block.lower())

    def test_non_dict_totals_value_also_falls_back(self):
        # Defensive: co_changed_totals present but the wrong shape (a list,
        # say, from some future or malformed producer) must be treated the
        # same as absent, via isinstance, never coerced.
        self.trace["co_changed_totals"] = ["not", "a", "dict"]
        html = render.render(self.trace, _VERDICT, lang="en")
        block = _hint_block(html)
        self.assertIn("payment_test.py", block)
        self.assertNotIn("capped", block.lower())

    def test_bool_total_for_one_sha_is_not_read_as_a_path_count(self):
        # bool is an int subclass in Python (isinstance(True, int) is
        # True), so a co_changed_totals entry of True must not be read as
        # a path count of 1 -- see render.py's isinstance(total, int)
        # guard, which now also excludes bool, matching the stance
        # patch.py's _int_or_none already takes on the same value shape.
        #
        # Two cited commits: sha_a's total is the malformed True, sha_b's
        # total is a real, larger int. If True were read as 1, the
        # aggregate (1 + 10 = 11) would exceed total_shown (2) and the
        # report would disclose a wrong "2 of 11" cut instead of falling
        # back to the plain list the all-or-nothing stance requires when
        # any cited commit's total is unknown.
        other_sha = "b7d2e90" + "0" * 33
        self.trace["introduction_candidates"].append({
            "sha": other_sha, "why": "blame",
            "subject": "fix: unrelated cleanup",
            "date": "2020-01-01T00:00:00+00:00", "author": "Han",
            "author_email": "han@example.com", "files_changed": 1,
        })
        self.trace["co_changed"].append({"path": "cleanup_test.py", "sha": other_sha})
        self.trace["co_changed_totals"] = {_SHA: True, other_sha: 10}
        verdict = dict(_VERDICT)
        verdict["evidence"] = [
            {"type": "commit", "ref": "a3f8c21", "note": "introduced during incident"},
            {"type": "commit", "ref": "b7d2e90", "note": "also introduced"},
        ]
        html = render.render(self.trace, verdict, lang="en")
        block = _hint_block(html)
        self.assertIn("payment_test.py", block)
        self.assertIn("cleanup_test.py", block)
        self.assertNotIn("capped", block.lower())
        self.assertNotIn("11", block)


if __name__ == "__main__":
    unittest.main()
