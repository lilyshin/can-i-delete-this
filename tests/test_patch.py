"""A keep-comment as a patch file the user applies themselves.

The load-bearing test in here is not that the diff looks right, it is that
`git apply` accepts it and the comment lands directly above the target
line with the target's own indentation. A patch that reads correctly and
is rejected by `git apply` is the failure this module exists to catch, so
these tests run `git apply` for real against a fixture repository.

`patch.build` itself never runs git and never writes to the target file
(see patch.py's module docstring): everything below either reads the diff
it returns or applies that diff with git in a throwaway fixture.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import artifacts
import make_fixture_repo
import patch
import trace as tracer
import verdict as verdict_schema

SCRIPTS = Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"

# The keep comment an agent would have written into the verdict: the same
# two lines the skeleton has, so a test that only cares about shape reads
# the same as it did, plus the incident reference an agent adds and a
# skeleton cannot know.
_KEEP_TEXT = (
    "KEEP: hotfix: prevent double charge (#4127), incident INC-4127.",
    "The retry path replays this branch; deleting it re-opens the incident.",
)


def _verdict(sha, *, grade="danger", content=None, marker="#"):
    """A verdict `verdict.validate()` accepts, artifact and all.

    The artifact block is not decoration here: `validate` requires
    `artifact.content` to be a non-empty string, and `patch.py` inserts
    that content when it is there, so a helper without one would test a
    shape the schema rejects and would miss which text the patch carries.

    `content` defaults to a keep comment in `marker`'s syntax, so a target
    whose comment marker is not `#` has to say so (`marker="//"`) exactly
    as a real agent would have to. Pass `content` to insert something
    else, including something that is not a comment at all.
    """
    if content is None:
        content = "\n".join(marker + " " + line for line in _KEEP_TEXT)
    return {
        "grade": grade,
        "summary": "This guard prevents a double charge.",
        "evidence": [{"type": "commit", "ref": sha, "role": "introduced"}],
        "conditions": ["the duplicate guard is removed upstream"],
        "artifact": {"kind": verdict_schema.ARTIFACT_KINDS[grade],
                     "content": content},
    }


def _verdict_without_artifact(sha, *, grade="danger"):
    """A verdict carrying no artifact block at all.

    `verdict.validate()` rejects this, but `patch.py` tolerates it by
    falling back to `artifacts.skeleton`, the same precedence
    `artifacts.py`'s CLI applies. The tests below that are about the
    skeleton itself, rather than about the text the agent approved, use
    this so the fallback is what they exercise.
    """
    data = _verdict(sha, grade=grade)
    del data["artifact"]
    return data


def _apply(repo, diff):
    """Write `diff` to a file and run `git apply` on it, the way a user
    would. Returns the CompletedProcess so a test can assert on failure
    text as well as success."""
    patch_file = os.path.join(repo, "keep.patch")
    with open(patch_file, "w", encoding="utf-8") as fh:
        fh.write(diff)
    return subprocess.run(["git", "apply", "keep.patch"], cwd=repo,
                          capture_output=True, text=True)


def _read(repo, path):
    """`newline=""` because one fixture file is CRLF and universal-newline
    translation would hide exactly what that fixture is for."""
    with open(os.path.join(repo, path), encoding="utf-8", newline="") as fh:
        return fh.read()


class _FixtureCase(unittest.TestCase):
    """A fresh fixture repository per test: several of these edit the
    working tree or apply a patch to it, and a shared repo would leak
    that into the next test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_patch_targets(self.tmp.name)
        self.repo = self.info["repo"]

    def target(self, key):
        return self.info[key]

    def trace_for(self, key):
        """A real trace of one fixture target, snippet and all. Built by
        trace.py rather than by hand so these tests keep consuming the
        JSON shape trace.py actually emits."""
        t = self.target(key)
        return tracer.trace(self.repo, t["path"], t["start"], t["end"])

    def _apply_above_target(self, key, marker, lang="en", verdict_data=None):
        t = self.target(key)
        before = _read(self.repo, t["path"]).split("\n")

        if verdict_data is None:
            verdict_data = _verdict(self.info["sha"], marker=marker)
        diff = patch.build(self.trace_for(key), verdict_data,
                           repo=self.repo, lang=lang)
        result = _apply(self.repo, diff)
        self.assertEqual(result.returncode, 0,
                         "git apply rejected the patch: " + result.stderr)

        after = _read(self.repo, t["path"]).split("\n")
        at = t["start"] - 1  # 0-based index of the target line
        inserted = len(after) - len(before)
        self.assertGreaterEqual(inserted, 1, "nothing was inserted")

        # Everything above the insertion point, and everything from the
        # target line down, is byte-identical.
        self.assertEqual(after[:at], before[:at])
        self.assertEqual(after[at + inserted:], before[at:])

        block = after[at:at + inserted]
        for line in block:
            self.assertTrue(line.startswith(t["indent"] + marker + " "),
                            "not an indented comment: " + repr(line))
        return t, block, after


class TestPatchApplies(_FixtureCase):
    """`git apply` accepts the patch, and the comment lands where it was
    supposed to: directly above the target line, at the target line's own
    indentation, with nothing else in the file touched.

    The keep comment is more than one line (a KEEP line plus a guard or a
    warning line), so "directly above" means the whole block sits between
    the line before the target and the target itself.
    """

    def test_python_patch_applies_and_lands_above_the_target(self):
        t, block, after = self._apply_above_target("python", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_kotlin_patch_uses_the_kotlin_marker(self):
        t, block, after = self._apply_above_target("kotlin", "//")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)], "            return")

    def test_sql_patch_uses_the_sql_marker(self):
        t, block, after = self._apply_above_target("sql", "--")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "    amount numeric(12, 2) not null,")

    def test_target_on_the_first_line_of_the_file(self):
        """No context above the insertion point at all, so the hunk starts
        at line 1 with a leading count of zero unchanged lines."""
        t, block, after = self._apply_above_target("head", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[len(block)], "import legacy_shim")

    def test_target_on_the_last_line_of_a_file_with_no_trailing_newline(self):
        t, block, after = self._apply_above_target("tail", "#")
        self.assertEqual(after[t["start"] - 1 + len(block)], "    return run(retries=3)")
        # The file had no trailing newline and must still have none.
        self.assertFalse(_read(self.repo, t["path"]).endswith("\n"))

    def test_korean_path_applies(self):
        t, block, after = self._apply_above_target("korean", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_korean_artifact_applies(self):
        """`--lang ko` reaches the comment text itself, which it can only do
        through the skeleton: a verdict's own content is inserted in the
        language the agent wrote it in, so this uses the fallback."""
        t, block, after = self._apply_above_target(
            "python", "#", lang="ko",
            verdict_data=_verdict_without_artifact(self.info["sha"]))
        self.assertIn("유지:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_crlf_file_applies_and_keeps_one_line_ending_style(self):
        """The trace's snippet lost the "\\r" to `str.splitlines()` and the
        working tree still has it, which must not read as "the target
        moved"; and the inserted comment must not leave the file with two
        line ending styles."""
        t, block, _after = self._apply_above_target("crlf", "#")
        for line in block:
            self.assertTrue(line.endswith("\r"), repr(line))
        raw = Path(os.path.join(self.repo, t["path"])).read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"),
                         "a bare LF line ending was introduced into a CRLF file")

    def test_multi_line_target_puts_the_comment_above_its_first_line(self):
        t, block, after = self._apply_above_target("block", "#")
        self.assertIn("KEEP:", block[0])
        self.assertEqual(after[t["start"] - 1 + len(block)],
                         "    if order.already_charged:")
        # The other three lines of the span are untouched and still in
        # order underneath it.
        self.assertEqual(after[t["start"] + len(block)],
                         "        log.info('duplicate charge blocked')")
        self.assertEqual(after[t["start"] + 2 + len(block)],
                         "        return {'status': 'duplicate'}")

    def test_the_whole_skeleton_block_is_inserted_not_just_its_first_line(self):
        """The fallback path: with no artifact content to insert, every line
        of the skeleton goes in, not only the KEEP line."""
        info = self.trace_for("python")
        no_artifact = _verdict_without_artifact(self.info["sha"])
        expected = artifacts.skeleton("danger", info, no_artifact["evidence"])
        t, block, _after = self._apply_above_target("python", "#",
                                                   verdict_data=no_artifact)
        self.assertEqual(len(block), len(expected.split("\n")))
        self.assertEqual([line.strip() for line in block],
                         [line.strip() for line in expected.split("\n")])


class TestPatchCarriesTheVerdictsOwnComment(_FixtureCase):
    """The text in the patch is the text the user was shown.

    A `danger` verdict's `artifact.content` is what the agent wrote and what
    `render.py` and `artifacts.py` display: the reasoning, the incident
    link, the reason not to delete. Rebuilding the skeleton here instead
    would put a second, quietly different comment into the file, and the
    documentation's claim that the patch carries the same comment would be
    false.
    """

    def test_the_helper_verdict_is_one_the_schema_accepts(self):
        """The shape these tests run against, checked against verdict.py
        itself: a helper the validator would reject cannot say anything
        about what happens to a real verdict."""
        verdict_schema.validate(_verdict(self.info["sha"]))
        for grade in ("conditional", "safe", "unknown"):
            verdict_schema.validate(_verdict(self.info["sha"], grade=grade))

    def test_patch_inserts_the_verdicts_content_not_the_skeleton(self):
        content = ("# KEEP: incident INC-4127, double charge on payment retry.\n"
                   "# The retry path replays this branch. Ask #billing first.")
        t, block, _after = self._apply_above_target(
            "python", "#",
            verdict_data=_verdict(self.info["sha"], content=content))
        self.assertEqual([line.strip() for line in block],
                         [line.strip() for line in content.split("\n")])
        skeleton = artifacts.skeleton("danger", self.trace_for("python"),
                                      _verdict(self.info["sha"])["evidence"])
        self.assertNotIn(skeleton.split("\n")[0], "\n".join(block))

    def test_content_with_a_trailing_newline_still_applies(self):
        """A trailing newline in the JSON string is a line terminator, not a
        blank line the marker check should refuse."""
        content = "# KEEP: incident INC-4127, double charge on retry.\n"
        t, block, _after = self._apply_above_target(
            "python", "#",
            verdict_data=_verdict(self.info["sha"], content=content))
        self.assertEqual(len(block), 1)


class TestPatchNeverWritesTheTargetFile(_FixtureCase):
    """The whole reason this feature is allowed to exist: it produces a
    patch, it does not edit the user's code."""

    def test_build_leaves_the_target_file_untouched(self):
        t = self.target("python")
        before = _read(self.repo, t["path"])
        patch.build(self.trace_for("python"), _verdict(self.info["sha"]),
                    repo=self.repo)
        self.assertEqual(_read(self.repo, t["path"]), before)

    def test_build_leaves_the_working_tree_clean(self):
        patch.build(self.trace_for("python"), _verdict(self.info["sha"]),
                    repo=self.repo)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo,
                                capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout.strip(), "")


class TestPatchShape(_FixtureCase):
    """The diff's own text, for the parts a test above cannot see once
    git has applied it."""

    def _diff(self, key, **kwargs):
        return patch.build(self.trace_for(key), _verdict(self.info["sha"]),
                           repo=self.repo, **kwargs)

    def test_header_names_the_target_path_on_both_sides(self):
        diff = self._diff("python")
        lines = diff.splitlines()
        self.assertEqual(lines[0], "diff --git a/billing/fee.py b/billing/fee.py")
        self.assertEqual(lines[1], "--- a/billing/fee.py")
        self.assertEqual(lines[2], "+++ b/billing/fee.py")
        self.assertTrue(lines[3].startswith("@@ -"))

    def test_every_added_line_carries_the_comment_marker(self):
        info = self.trace_for("python")
        # A co-changed test on the cited commit makes skeleton() emit the
        # guard line as well as the KEEP line, so the patch has more than
        # one added line to check. The verdict carries no content of its
        # own, so the skeleton is what lands in the patch.
        info["co_changed"] = [{"path": "tests/test_fee.py", "sha": self.info["sha"]}]
        diff = patch.build(info, _verdict_without_artifact(self.info["sha"]),
                           repo=self.repo)
        added = [l[1:] for l in diff.splitlines() if l.startswith("+")
                 and not l.startswith("+++")]
        self.assertGreater(len(added), 1)
        for line in added:
            self.assertTrue(line.startswith("        # "),
                            "added line is not an indented comment: " + repr(line))

    def test_context_lines_are_the_lines_around_the_target(self):
        diff = self._diff("python")
        context = [l[1:] for l in diff.splitlines()[4:] if l.startswith(" ")]
        self.assertIn("    if order.already_charged:", context)
        self.assertIn("    order.mark_processed()", context)

    def test_context_lines_come_from_the_working_tree_not_from_the_trace(self):
        """The claim patch.py exists for (see its module docstring): the
        context is read from the file on disk, because that is what
        `git apply` matches against, and a patch built from what the trace
        recorded is rejected the moment the working tree has an uncommitted
        edit.

        The two can only be told apart where they disagree, and the strict
        recorded-window check refuses every disagreement inside the window.
        So the edit goes just past the end of the window: `edge.py`'s target
        sits two lines from the end of the file, its recorded snippet is
        clamped there, and the patch's three lines of trailing context reach
        one line further. An uncommitted line appended on disk therefore has
        to appear in the hunk, and nothing in the trace could have supplied
        it.
        """
        t = self.target("edge")
        full = os.path.join(self.repo, t["path"])
        uncommitted = "    # uncommitted while investigating"
        with open(full, "a", encoding="utf-8") as fh:
            fh.write(uncommitted + "\n")

        info = self.trace_for("edge")
        self.assertNotIn(uncommitted, info["snippet"]["lines"],
                         "the fixture's snippet already knows the edit, so "
                         "this test cannot tell disk from trace")

        diff = patch.build(info, _verdict(self.info["sha"]), repo=self.repo)
        context = [l[1:] for l in diff.splitlines()[4:] if l.startswith(" ")]
        self.assertIn(uncommitted, context)
        result = _apply(self.repo, diff)
        self.assertEqual(result.returncode, 0,
                         "git apply rejected the patch: " + result.stderr)

    def test_no_newline_at_end_of_file_is_declared(self):
        diff = self._diff("tail")
        self.assertIn("\\ No newline at end of file", diff)

    def test_no_newline_marker_is_absent_for_an_ordinary_file(self):
        self.assertNotIn("\\ No newline", self._diff("python"))

    def test_hunk_header_counts_match_the_lines_that_follow(self):
        diff = self._diff("python").splitlines()
        header = diff[3]
        body = diff[4:]
        old = len([l for l in body if l.startswith((" ", "-"))])
        new = len([l for l in body if l.startswith((" ", "+"))])
        self.assertEqual(header, "@@ -3,6 +3,8 @@")
        self.assertEqual(header.split()[1], "-3,{}".format(old))
        self.assertEqual(header.split()[2], "+3,{}".format(new))

    def test_patch_ends_with_a_newline(self):
        self.assertTrue(self._diff("python").endswith("\n"))


class TestRefusals(_FixtureCase):
    """A wrong patch is worse than no patch, so every doubt is a refusal
    with a reason a person can act on."""

    def _refuse(self, trace_data, verdict_data, **kwargs):
        with self.assertRaises(patch.Refused) as caught:
            patch.build(trace_data, verdict_data, repo=self.repo, **kwargs)
        self.assertTrue(str(caught.exception).strip(),
                        "a refusal with no reason is not a reason")
        return caught.exception

    def test_grade_safe_is_refused(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="safe"))
        self.assertEqual(refused.code, "not-danger")

    def test_grade_conditional_is_refused(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="conditional"))
        self.assertEqual(refused.code, "not-danger")

    def test_grade_unknown_is_refused(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="unknown"))
        self.assertEqual(refused.code, "not-danger")

    def test_unavailable_snippet_is_refused(self):
        info = self.trace_for("python")
        info["snippet"] = {"available": False, "reason": "missing-at-head"}
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "no-snippet")

    def test_form_feed_far_past_the_snippet_window_is_refused(self):
        """I2: before `trace.py` detected the form feed itself, only the
        line-number disagreement it causes (`str.splitlines()` treats a
        form feed as a line break; `patch.py`'s `"\\n"`-only split does
        not) could trigger a refusal, and only when that disagreement fell
        inside the snippet's own recorded window. This fixture's form feed
        sits seventeen lines past the target (well outside the window), so
        before this fix the window matched the working tree by
        coincidence and a patch was built anyway. It must now refuse
        unconditionally: `trace.py` marks the snippet unavailable the
        moment it sees the form feed, regardless of where it sits."""
        info = self.trace_for("form_feed")
        self.assertEqual(info["snippet"], {"available": False, "reason": "form-feed"})
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "no-snippet")

    def test_unknown_extension_is_refused_rather_than_left_markerless(self):
        info = self.trace_for("docs")
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "no-marker")

    def test_target_beyond_the_end_of_the_file_is_refused(self):
        info = self.trace_for("python")
        info["target"]["start"] = 400
        info["target"]["end"] = 400
        info["snippet"]["target_start"] = 400
        info["snippet"]["target_end"] = 400
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "out-of-range")

    def test_edited_working_tree_is_refused(self):
        """The file moved on since the investigation, so the recorded line
        numbers may point somewhere else now."""
        t = self.target("python")
        info = self.trace_for("python")
        full = os.path.join(self.repo, t["path"])
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("# a new line at the top pushes everything down\n" + text)
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_edited_target_line_itself_is_refused(self):
        t = self.target("python")
        info = self.trace_for("python")
        full = os.path.join(self.repo, t["path"])
        with open(full, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        lines[t["start"] - 1] = "        return {'status': 'dupe'}"
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def _edit_line(self, key, lineno, text):
        """Replace one line of a fixture file on disk, in place."""
        full = os.path.join(self.repo, self.target(key)["path"])
        with open(full, encoding="utf-8", newline="") as fh:
            lines = fh.read().split("\n")
        lines[lineno - 1] = text
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(lines))

    def test_edit_in_the_middle_of_a_multi_line_target_is_refused(self):
        """A four-line target whose first line is untouched but whose third
        line changed. The conclusion was reached about the whole span, so
        it no longer describes what is on disk, and a KEEP above line 5
        would assert something about code nobody traced. Comparing only
        the first line of the span would miss this."""
        info = self.trace_for("block")
        self._edit_line("block", 7, "        metrics.count('charge.dup')")
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_edit_at_the_end_of_a_multi_line_target_is_refused(self):
        info = self.trace_for("block")
        self._edit_line("block", 8, "        return {'status': 'dupe'}")
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_untouched_multi_line_target_is_not_refused(self):
        """The other half of the pair: nothing in the span changed, so the
        strictness above must not be refusing everything."""
        info = self.trace_for("block")
        self.assertIn("diff --git a/block.py",
                      patch.build(info, _verdict(self.info["sha"]), repo=self.repo))

    # The reordered file: two methods of the same shape swapped, which is
    # an ordinary refactor, and after it line 6 is another method's bare
    # `return`. The recorded target text matches there line for line, so a
    # check that compared only the target's own lines builds a patch and
    # `git apply` takes it: the KEEP comment lands above code nobody
    # traced, which is the misattribution this whole project refuses.
    _REORDERED_KOTLIN = (
        "package billing\n"
        "\n"
        "class Ledger {\n"
        "    fun refund(order: Order) {\n"
        "        if (order.refunded) {\n"
        "            return\n"
        "        }\n"
        "        order.markRefunded()\n"
        "    }\n"
        "\n"
        "    fun charge(order: Order) {\n"
        "        if (order.alreadyCharged) {\n"
        "            return\n"
        "        }\n"
        "        order.markProcessed()\n"
        "    }\n"
        "}\n"
    )

    def test_reordered_file_matching_the_target_text_is_refused(self):
        info = self.trace_for("reorder")
        t = self.target("reorder")
        on_disk = self._REORDERED_KOTLIN.split("\n")
        self.assertEqual(on_disk[t["start"] - 1],
                         info["snippet"]["lines"][t["start"]
                                                 - info["snippet"]["start_line"]],
                         "the reordered file must still match the target's own "
                         "line, or this test refuses for the wrong reason")

        with open(os.path.join(self.repo, t["path"]), "w",
                  encoding="utf-8") as fh:
            fh.write(self._REORDERED_KOTLIN)

        refused = self._refuse(info, _verdict(self.info["sha"], marker="//"))
        self.assertEqual(refused.code, "target-moved")

    def test_unreordered_file_still_produces_a_patch(self):
        """The other half of the pair: the same fixture, untouched, has to
        produce a patch. A check that refused this would be refusing
        everything rather than catching the reorder."""
        info = self.trace_for("reorder")
        diff = patch.build(info, _verdict(self.info["sha"], marker="//"),
                           repo=self.repo)
        self.assertIn("diff --git a/Ledger.kt", diff)
        result = _apply(self.repo, diff)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_edit_to_a_context_line_outside_the_target_is_refused(self):
        """The narrow version of the reorder: one line the trace recorded
        next to the target, changed on disk, with the target itself
        untouched. The recorded window is evidence about where the target
        is, so a disagreement anywhere in it is a refusal."""
        info = self.trace_for("python")
        self._edit_line("python", 5, "    if order.charged_already:")
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_edit_below_the_target_inside_the_window_is_refused(self):
        info = self.trace_for("python")
        self._edit_line("python", 8, "    return order.total_amount")
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "target-moved")

    def test_content_that_is_not_a_comment_is_refused(self):
        """An agent can write prose into `artifact.content` as easily as a
        comment, and prose in a source file is a syntax error. The patch is
        refused rather than reformatted: artifacts.py still prints the text,
        so the refusal costs one step, while a file that no longer compiles
        costs a great deal more."""
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(
            self.info["sha"],
            content="This guard prevents a double charge. See INC-4127."))
        self.assertEqual(refused.code, "not-a-comment")

    def test_content_whose_marker_is_another_languages_is_refused(self):
        """A `//` comment above a Python line is not a comment, so the check
        is per target file, not "does it look like a comment somewhere"."""
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(
            self.info["sha"], content="// KEEP: incident INC-4127."))
        self.assertEqual(refused.code, "not-a-comment")

    def test_undecodable_file_is_refused(self):
        info = self.trace_for("python")
        info["target"]["path"] = self.target("binary")["path"]
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "binary-file")

    def test_valid_utf8_holding_a_nul_byte_is_refused(self):
        """git treats a NUL byte as the signal that a file is binary even
        when it decodes cleanly, and that is the only case the NUL check
        catches: `blob.py` above never reaches it, since it fails to decode
        first."""
        info = self.trace_for("python")
        info["target"]["path"] = self.target("nul")["path"]
        with open(os.path.join(self.repo, self.target("nul")["path"]), "rb") as fh:
            raw = fh.read()
        self.assertIn(b"\x00", raw)
        raw.decode("utf-8")  # decodes cleanly, so only the NUL check can refuse it
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "binary-file")

    def test_missing_file_is_refused(self):
        info = self.trace_for("python")
        os.remove(os.path.join(self.repo, self.target("python")["path"]))
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "missing-file")

    def test_path_outside_the_repository_is_refused(self):
        info = self.trace_for("python")
        info["target"]["path"] = "../outside.py"
        refused = self._refuse(info, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "outside-repo")

    def test_unresolved_citation_is_refused(self):
        """skeleton() answers an unresolved citation with a warning
        paragraph, not a comment. Inserting that into source would be a
        syntax error, and inserting a guessed attribution instead would be
        the misattribution this project exists to avoid. The verdict carries
        no content of its own, so the skeleton is what gets checked."""
        info = self.trace_for("python")
        refused = self._refuse(
            info, _verdict_without_artifact("deadbee" + "0" * 33))
        self.assertEqual(refused.code, "not-a-comment")

    def test_ambiguous_no_evidence_citation_is_refused(self):
        """A verdict with no evidence at all, against a trace with more
        than one introduction_candidates entry, is the exact shape the
        0.9.2 field run got wrong: skeleton() used to fall back to the
        chronologically oldest candidate and build a confident KEEP
        comment naming it, citing a commit that might have nothing to do
        with the target. artifacts.py now routes this through the same
        unresolved-citation warning an unresolved ref gets (see
        tests/test_artifacts_ambiguous_citation.py), and that text is not
        a comment, so patch.py must refuse it the same way."""
        info = self.trace_for("python")
        info["introduction_candidates"] = info["introduction_candidates"] + [{
            "sha": "b1b1b1b" + "1" * 33, "subject": "unrelated change",
            "date": "2020-01-01T00:00:00+00:00", "author": "Someone",
            "author_email": "someone@example.com", "why": "pickaxe",
        }]
        refused = self._refuse(info, {"grade": "danger"})
        self.assertEqual(refused.code, "not-a-comment")

    def test_not_a_comment_message_names_all_three_causes(self):
        """I4: the message used to name two causes ("its citation resolves
        to no commit in this trace ... or to no commit tagged as the
        introduction"), and both were false for the ambiguous case above
        (no citation was made at all). Pinned verbatim so a future edit
        that drops the third cause, or any of the other two, is caught."""
        info = self.trace_for("python")
        refused = self._refuse(
            info, _verdict_without_artifact("deadbee" + "0" * 33))
        self.assertEqual(str(refused), (
            "The keep comment for this verdict is not a comment: at "
            "least one of its lines does not start with #. Either the "
            "verdict's own artifact content is not comment lines in "
            "this file's syntax, or (when it carries none) its citation "
            "resolves to no commit in this trace, resolves to no commit "
            "tagged as the introduction, or was never made at all while "
            "the trace offered more than one introduction candidate to "
            "choose from. It cannot be inserted into source. Run "
            "artifacts.py to read what it says and act on that instead."
        ))

    def test_not_a_comment_message_is_translated(self):
        info = self.trace_for("python")
        refused = self._refuse(
            info, _verdict_without_artifact("deadbee" + "0" * 33), lang="ko")
        self.assertEqual(str(refused), (
            "이 검증(verdict)의 KEEP 주석이 주석이 아닙니다. #로 시작하지 않는 줄이 "
            "있습니다. 검증의 artifact content가 이 파일 문법의 주석 줄이 아니거나, "
            "content가 없는 경우라면 인용한 커밋이 이 trace에 없거나, 도입 커밋으로 "
            "표시된 것이 없거나, 후보가 여럿인데도 근거로 아무 커밋도 인용하지 않은 "
            "경우입니다. 소스에 넣을 수 없으니 artifacts.py를 실행해 내용을 읽고 "
            "그에 따라 처리하세요."
        ))

    def test_malformed_trace_is_refused(self):
        refused = self._refuse({"target": {}}, _verdict(self.info["sha"]))
        self.assertEqual(refused.code, "malformed-trace")

    def test_verdict_with_no_grade_is_refused_as_malformed(self):
        """A grade that is not one of verdict.py's four words is a broken
        verdict, not a grade this declines to serve, so it does not get
        quoted back inside "grade is X, not danger"."""
        info = self.trace_for("python")
        refused = self._refuse(info, {"summary": "no grade here",
                                      "evidence": []})
        self.assertEqual(refused.code, "malformed-verdict")

    def test_declined_grade_is_named_in_the_reason(self):
        info = self.trace_for("python")
        refused = self._refuse(info, _verdict(self.info["sha"], grade="safe"))
        self.assertIn("safe", str(refused))

    def test_refusal_reason_is_translated(self):
        info = self.trace_for("python")
        en = self._refuse(info, _verdict(self.info["sha"], grade="safe"))
        ko = self._refuse(info, _verdict(self.info["sha"], grade="safe"), lang="ko")
        self.assertEqual(en.code, ko.code)
        self.assertNotEqual(str(en), str(ko))


class TestCli(_FixtureCase):
    """The CLI is how the skill calls this, so it gets the same scrutiny
    as the function."""

    def _write_json(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return path

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "patch.py"), *args],
            capture_output=True, text=True)

    def test_prints_the_patch_to_stdout(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diff --git a/billing/fee.py", result.stdout)

    def test_out_writes_a_patch_file_that_applies(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        out = os.path.join(self.tmp.name, "keep.patch")
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        applied = subprocess.run(["git", "apply", out], cwd=self.repo,
                                 capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)

    def test_repo_defaults_to_the_one_the_trace_recorded(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        result = self._run("--trace", t, "--verdict", v)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diff --git a/billing/fee.py", result.stdout)

    def test_refusal_exits_nonzero_with_the_reason_on_stderr(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json",
                             _verdict(self.info["sha"], grade="safe"))
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("danger", result.stderr)

    def test_out_pointing_at_the_target_file_is_refused(self):
        """`--out` is the only file this tool opens for writing, so the one
        promise it makes stays true even when the user's own argument aims
        it at the source file."""
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        target_path = self.target("python")["path"]
        before = _read(self.repo, target_path)

        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", os.path.join(self.repo, target_path))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(target_path, result.stderr)
        self.assertEqual(_read(self.repo, target_path), before)

    def test_out_pointing_at_the_target_file_by_a_roundabout_path_is_refused(self):
        """The check resolves the path, so `billing/../billing/fee.py` is
        the same refusal and not a way around it."""
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        target_path = self.target("python")["path"]
        before = _read(self.repo, target_path)

        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", os.path.join(self.repo, "billing", "..",
                                                 "billing", "fee.py"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(_read(self.repo, target_path), before)

    def test_out_pointing_at_some_other_file_is_the_users_business(self):
        """Only the target file is protected. Any other path the user names
        is a patch file, including one inside the repository."""
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json", _verdict(self.info["sha"]))
        out = os.path.join(self.repo, "billing", "keep.patch")
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(out))

    def test_refusal_writes_no_out_file(self):
        t = self._write_json("trace.json", self.trace_for("python"))
        v = self._write_json("verdict.json",
                             _verdict(self.info["sha"], grade="safe"))
        out = os.path.join(self.tmp.name, "keep.patch")
        result = self._run("--trace", t, "--verdict", v, "--repo", self.repo,
                           "--out", out)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
