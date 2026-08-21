"""Regression tests for N2 of the second re-review round.

I2's original fix (trace.py detecting a form feed and marking the
target's snippet unavailable, so `patch.py`'s `no-snippet` refusal fires
regardless of where the resulting line-number disagreement would have
fallen) tested for `"\\x0c"` alone. `str.splitlines()` treats eight other
characters as a line break the same way a form feed is, and a lone `"\r"`
(one not immediately followed by `"\n"`) is a ninth case; none of the
other eight, nor the ninth, made `trace.py` refuse before this fix, so a
file containing one of them reproduced the exact pre-I2 hazard: a wrong
sha and a wrong subject landing in a `KEEP:` comment whenever
`_check_unmoved`'s content comparison happened to match by coincidence.

`tests/test_patch.py::TestRefusals::test_form_feed_far_past_the_snippet_window_is_refused`
and its `test_vertical_tab_far_past_the_snippet_window_is_refused` sibling
cover the real end-to-end shape (a real git repo, a real trace, a real
`patch.py` refusal) for two of the nine characters. This file covers all
nine directly against `trace._has_splitlines_divergence`, the pure
function the fix added, since building nine git fixtures to exercise the
same one-line check would be a lot of machinery for what a plain string
in and a bool out already tests completely.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import trace as tracer

# The eight characters `_SPLITLINES_ONLY_BREAKS` names, plus the ninth
# case (a lone "\r") handled separately by `_LONE_CR`. Listed here by
# name, not just imported as the constant, so a change to the constant
# that silently drops one of the nine is caught by this file rather than
# by both sides agreeing with each other.
_VERTICAL_TAB = "\x0b"
_FORM_FEED = "\x0c"
_FILE_SEPARATOR = "\x1c"
_GROUP_SEPARATOR = "\x1d"
_RECORD_SEPARATOR = "\x1e"
_NEXT_LINE = "\x85"
_LINE_SEPARATOR = "\u2028"
_PARAGRAPH_SEPARATOR = "\u2029"

_EIGHT_ALWAYS_BREAK_CHARS = (
    _VERTICAL_TAB, _FORM_FEED, _FILE_SEPARATOR, _GROUP_SEPARATOR,
    _RECORD_SEPARATOR, _NEXT_LINE, _LINE_SEPARATOR, _PARAGRAPH_SEPARATOR,
)


def _working_tree_line_count(text):
    """The line count `patch.py`'s own `_read_working_tree` would compute
    for `text`: split on "\\n" only, then drop the trailing empty element
    a final newline produces (patch.py does the same before comparing).
    Reimplemented here, deliberately, rather than imported: this file
    checks `trace._has_splitlines_divergence` against the actual
    divergence it claims to detect, not against another call to itself.
    """
    lines = text.split("\n")
    if len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return lines


def _really_diverges(text):
    return len(text.splitlines()) != len(_working_tree_line_count(text))


class TestEachOfTheEightAlwaysBreakCharactersIsDetected(unittest.TestCase):
    """Each of these, alone, in the middle of an otherwise ordinary file,
    makes `str.splitlines()` count one more line than a `"\\n"`-only
    split would -- the exact shape `_has_splitlines_divergence` exists to
    catch. Mutation: hard-coding the check to only `"\\x0c"` (the
    original I2 fix) turns every case here except form feed red."""

    def test_each_character_is_a_real_divergence_and_is_detected(self):
        for char in _EIGHT_ALWAYS_BREAK_CHARS:
            with self.subTest(char=hex(ord(char))):
                text = "a\nb" + char + "c\nd\n"
                # Premise check: this shape actually diverges under the
                # real methods trace.py and patch.py use, not just under
                # this test's own assumption about the character.
                self.assertTrue(_really_diverges(text),
                                "test fixture does not actually diverge")
                self.assertTrue(tracer._has_splitlines_divergence(text))

    def test_none_of_the_eight_false_positive_on_ordinary_text(self):
        # The other half of the pair: a file with none of these
        # characters must not be flagged, or the detection would refuse
        # every ordinary file and I2's fix would be useless.
        text = "def charge(order):\n    return order.total\n"
        self.assertFalse(_really_diverges(text))
        self.assertFalse(tracer._has_splitlines_divergence(text))


class TestLoneCarriageReturnIsTheNinthCase(unittest.TestCase):
    """A "\\r" not immediately followed by "\\n" is also a line break to
    `str.splitlines()` but not to a `"\\n"`-only split; "\\r\\n" itself is
    a single break to both (a CRLF file, which this project already
    supports, must not be flagged), so the two are tested as a pair."""

    def test_lone_cr_diverges_and_is_detected(self):
        text = "a\nb\rc\nd\n"
        self.assertTrue(_really_diverges(text))
        self.assertTrue(tracer._has_splitlines_divergence(text))

    def test_crlf_does_not_diverge_and_is_not_flagged(self):
        text = "a\r\nb\r\nc\n"
        self.assertFalse(_really_diverges(text))
        self.assertFalse(tracer._has_splitlines_divergence(text))


if __name__ == "__main__":
    unittest.main()
