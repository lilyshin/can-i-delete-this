"""Regression test for final-review finding I1.

`artifacts._tests()` can return more than one test-looking path once
`noise.is_test_path` recognizes the capitalized `Test$` convention, because
that rule matches an A/B-experiment class like `ABTest.kt` just as readily
as a genuine test. Git's own path order is alphabetical, so a false
positive like `billing/ABTest.kt` can sort ahead of the genuine test that
actually guards the target. Naming only the first match (`tests[0]`) would
show the reader the false positive and never the real test, and then
`danger.guard_unverified` would say "no test guards this" while a real test
sat unmentioned in the same trace. This test builds that exact commit shape
with a real fixture repo and the real tracer, not a hand-built trace dict,
and confirms the rendered `danger` artifact names the genuine test.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import artifacts
import trace as tracer


class TestGuardLineNamesTheGenuineTestNotJustTheFalsePositive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = make_fixture_repo.build_guard_name_collision(self.tmp.name)
        self.result = tracer.trace(
            self.info["repo"], self.info["path"], self.info["line"], self.info["line"])

    def test_premise_false_positive_sorts_before_the_genuine_test(self):
        # Pin the shape the finding depends on: git's own (alphabetical)
        # order puts the Test$ false positive ahead of the real test, so a
        # fix that only ever looked at index 0 would never see the real one.
        co_changed_paths = [c["path"] for c in self.result["co_changed"]]
        self.assertEqual(co_changed_paths, [
            self.info["false_positive_path"], self.info["test_path"],
        ])

    def test_danger_guard_line_names_the_genuine_test(self):
        out = artifacts.skeleton("danger", self.result)
        self.assertIn(self.info["test_path"], out)
        self.assertIn(self.info["false_positive_path"], out)

    def test_guard_unverified_line_uses_the_plural_wording(self):
        # Two paths are named on the guard line, so the caveat below it
        # must read "none of these", not "it" -- the singular wording would
        # itself misreport how many candidates are being talked about.
        out = artifacts.skeleton("danger", self.result)
        self.assertIn("If none of these are tests, no test guards this", out)
        self.assertNotIn("If it is not a test, no test guards this", out)


if __name__ == "__main__":
    unittest.main()
