"""Regression tests for the fourth fix round: `scan.py` shares the exact
hazard `trace.py`/`patch.py` closed in the second and third rounds
(`tests/test_trace_line_break_divergence.py`), because it reads a file's
content the same way `trace.py` used to -- through `gitq.run_git`'s text
mode, whose universal-newline translation silently rewrites a lone "\r"
before anything downstream can see it -- and then numbers the file's
lines with `str.splitlines()` (`scanner.find_blocks`), while the
`git blame -L` call it pairs with counts the same file by git's own
"\n"-only convention. A character that makes the two disagree shifts
every line number `scan.py` reports after it, and shifts the blame
target along with it: the reviewer's own reproduction found a
commented-out block reported one line off, blamed through a `def` that
was never part of it.

Unlike `trace.py`/`patch.py`, there is no single verdict to refuse here,
so the fix is a skip: `scan.py` counts and discloses the file
(`files_skipped_irregular_line_break` in `limits`, a `notes` sentence)
rather than report it with numbers that might not match what git itself
would say about the same file.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import gitq
import scan as scanmod
import scanner


class TestDivergentFilesAreSkippedNotMisreported(unittest.TestCase):
    """Each case here first proves the hazard is real -- if this file
    were scanned anyway, `scanner.find_blocks` would report the block
    one line off from git's own numbering, the exact shape the reviewer
    reproduced -- and then confirms `scan.py` itself never does that:
    the file is counted and disclosed, and produces no candidate at all.
    Tying the "no candidate" assertion to a concrete premise about what
    the wrong numbers would be (rather than checking absence alone)
    means a mutation that removes the skip fails here specifically
    because a candidate with the wrong numbers reappeared, not merely
    because a counter went back to zero.
    """

    def _assert_skipped_not_misreported(self, divergent):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_scan_line_break_divergence(
                tmp, divergent=divergent)

            # Premise: scanning this file's real content directly (through
            # the same bytes-based read scan.py itself now uses) reproduces
            # the shifted numbering git would not agree with -- one line
            # off from `info["block_start"]`/`info["block_end"]`, which are
            # computed independently, by a plain "\n"-only count.
            raw = gitq.run_git_bytes(info["repo"], ["show", "HEAD:" + info["path"]])
            text = raw.decode("utf-8")
            marker = scanner.marker_for(info["path"])
            blocks = scanner.find_blocks(text, marker)
            self.assertEqual(len(blocks), 1, "premise: exactly one block")
            wrong_start = info["block_start"] + 1
            self.assertEqual(
                blocks[0].start, wrong_start,
                "premise: scanning this file directly must reproduce the "
                "shifted numbering (str.splitlines() treats the divergent "
                "character as a break, git's own \\n-only count does not)")

            data = scanmod.scan(info["repo"], ".")

        # Checked before the counter, deliberately: a mutation that
        # removes the skip must fail here, on a candidate reappearing at
        # `wrong_start` (the exact number the premise above just proved
        # this file would get), not merely on a counter reading zero.
        matching = [c for c in data["candidates"] if c["path"] == info["path"]]
        self.assertEqual(
            matching, [],
            "the file must be skipped, not reported at the shifted line "
            "number ({}) the premise above just proved it would get if "
            "scanned anyway".format(wrong_start))
        self.assertEqual(data["limits"]["files_skipped_irregular_line_break"], 1,
                         data["limits"])
        self.assertTrue(
            any("unreliable" in n for n in data["notes"]), data["notes"])

    def test_lone_cr_before_a_block_is_skipped_not_misreported(self):
        self._assert_skipped_not_misreported(b"\r")

    def test_vertical_tab_before_a_block_is_skipped_not_misreported(self):
        # One representative of the other eight always-break characters;
        # all nine are covered at the predicate level by
        # test_trace_line_break_divergence.py, which both this module and
        # trace.py's snippet reader now share (gitq.has_splitlines_divergence).
        self._assert_skipped_not_misreported(b"\x0b")


class TestNegativeControlsScanNormallyWithCorrectNumbers(unittest.TestCase):
    """Neither a CRLF-only file (a real, ordinary line ending, not a lone
    divergent character) nor a plain LF file may be skipped: doing so
    would refuse to scan every Windows-authored file, or every ordinary
    one. Both must produce exactly one candidate, and -- the sharper
    check -- at the numbers git's own "\\n"-only counting agrees with,
    not merely "some" numbers.
    """

    def _assert_scanned_with_correct_numbers(self, divergent):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_scan_line_break_divergence(
                tmp, divergent=divergent)
            data = scanmod.scan(info["repo"], ".")
        self.assertEqual(data["limits"]["files_skipped_irregular_line_break"], 0,
                         data["limits"])
        self.assertEqual(data["limits"]["files_skipped_binary"], 0, data["limits"])
        matching = [c for c in data["candidates"] if c["path"] == info["path"]]
        self.assertEqual(len(matching), 1, data["candidates"])
        self.assertEqual(matching[0]["start"], info["block_start"])
        self.assertEqual(matching[0]["end"], info["block_end"])

    def test_crlf_file_is_scanned_with_correct_numbers(self):
        self._assert_scanned_with_correct_numbers(b"\r\n")

    def test_plain_lf_file_is_scanned_with_correct_numbers(self):
        self._assert_scanned_with_correct_numbers(b"")


if __name__ == "__main__":
    unittest.main()
