import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "skills", "can-i-delete-this", "scripts"))

import gitq  # noqa: E402
import make_fixture_repo  # noqa: E402
import scan as scanmod  # noqa: E402

NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


class ScanCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_commented_out(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestCandidates(ScanCase):

    def test_exactly_two_candidates(self):
        paths = [(c["path"], c["start"], c["end"]) for c in self.data["candidates"]]
        self.assertEqual(len(self.data["candidates"]), 2, paths)

    def test_todo_run_is_not_a_candidate(self):
        for c in self.data["candidates"]:
            if c["path"] == "notes.py":
                self.assertGreater(c["start"], 4,
                                    "the TODO run occupies lines 1-4")

    def test_license_header_is_not_a_candidate(self):
        self.assertNotIn("licensed.py", [c["path"] for c in self.data["candidates"]])

    def test_vendored_path_is_skipped_and_counted(self):
        self.assertNotIn("vendor/thirdparty.py",
                          [c["path"] for c in self.data["candidates"]])
        self.assertEqual(self.data["limits"]["files_skipped_vendored"], 1)

    def test_candidate_carries_the_commenting_commit(self):
        c = next(c for c in self.data["candidates"] if c["path"] == "billing.py")
        commit = c["commented_out_by"]
        self.assertEqual(commit["sha"], self.info["outage_sha"])
        self.assertEqual(commit["subject"], "hotfix: 게이트웨이 장애로 재시도 비활성화")
        self.assertIn("#3391", commit["body"])

    def test_age_days_uses_the_injected_now(self):
        c = next(c for c in self.data["candidates"] if c["path"] == "billing.py")
        # 2021-06-14T09:12:00+09:00 (= 00:12Z) to 2026-08-13T00:00:00Z is
        # 1885 days and 23:48, so .days is 1885, not 1886. Both the fixture
        # date and NOW are fixed, so this value is exact.
        self.assertEqual(c["commented_out_by"]["age_days"], 1885)


class TestOrderingAndLookFirst(ScanCase):

    def test_oldest_first(self):
        self.assertEqual(self.data["candidates"][0]["path"], "billing.py")
        self.assertEqual(self.data["candidates"][1]["path"], "notes.py")

    def test_look_first_set_by_incident_vocabulary(self):
        by_path = {c["path"]: c for c in self.data["candidates"]}
        self.assertTrue(by_path["billing.py"]["look_first"])
        self.assertFalse(by_path["notes.py"]["look_first"])

    def test_look_first_is_not_a_grade(self):
        """스캔 출력에 등급 단어가 없어야 한다."""
        blob = str(self.data).lower()
        for word in ("safe to delete", '"safe"', '"danger"', '"conditional"'):
            self.assertNotIn(word, blob)


class TestLimits(ScanCase):

    def test_scan_scope_is_reported(self):
        limits = self.data["limits"]
        self.assertEqual(limits["files_scanned"], 3)
        self.assertEqual(limits["files_skipped_vendored"], 1)
        self.assertEqual(limits["files_skipped_unsupported"], 1)
        self.assertFalse(limits["candidate_cap_reached"])

    def test_too_large_and_missing_at_head_are_counted_in_limits(self):
        """Neither skip reason is exercised by this fixture, but both keys
        must exist and read 0 (not be absent): a caller reading `limits`
        programmatically cannot see a count that only ever appears as
        conditional free text in `notes`."""
        limits = self.data["limits"]
        self.assertIn("files_skipped_too_large", limits)
        self.assertIn("files_missing_at_head", limits)
        self.assertEqual(limits["files_skipped_too_large"], 0)
        self.assertEqual(limits["files_missing_at_head"], 0)

    def test_block_comment_boundary_is_disclosed(self):
        self.assertTrue(
            any("block comment" in n.lower() for n in self.data["notes"]),
            "the /* */ boundary must be stated, not left for the reader to "
            "discover by missing a block")

    def test_candidate_cap_is_enforced_and_disclosed(self):
        capped = scanmod.scan(self.info["repo"], ".", max_candidates=1, now=NOW)
        self.assertEqual(len(capped["candidates"]), 1)
        self.assertTrue(capped["limits"]["candidate_cap_reached"])


class TestUnsupportedExtensions(ScanCase):

    def test_unsupported_extension_is_counted_not_scanned(self):
        """README.rst contains two code-shaped comment lines (`def
        looks_like_code(x):` and `return x`; `pass` matches none of
        `scanner._CODE_SHAPE`'s patterns). It must be counted as skipped,
        and it must not produce a candidate: a language absent from
        COMMENT_MARKERS is not guessed at."""
        self.assertEqual(self.data["limits"]["files_skipped_unsupported"], 1)
        self.assertNotIn("README.rst",
                          [c["path"] for c in self.data["candidates"]])


class TestOrderingIsReal(unittest.TestCase):
    """`test_oldest_first` above would still pass with `scan()`'s sort key
    deleted entirely: `billing.py` sorts before `notes.py` both
    alphabetically and chronologically, and `ls-files` already lists them
    in that order. This fixture makes the two orders disagree, so only a
    real oldest-first sort can pass."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_ordering_probe(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_chronological_order_wins_over_alphabetical(self):
        paths = [c["path"] for c in self.data["candidates"]]
        # aaa_recent.py sorts first alphabetically (and is what ls-files
        # would list first); zzz_old.py's block is from 2019, three years
        # before aaa_recent.py's 2024 block, so it must lead the results.
        self.assertEqual(paths[0], "zzz_old.py", paths)
        self.assertEqual(paths[1], "aaa_recent.py", paths)


class TestOldestOfSeveralBlameShas(unittest.TestCase):
    """Every block in `build_commented_out` carries exactly one blame sha,
    so `touched_by_commits` is always 1 there and `_oldest`'s "pick the
    oldest of several, report how many" behavior is never exercised. A
    regression returning the newest sha instead of the oldest, or
    hardcoding `touched_by_commits = 1`, would pass every other test in
    this file."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_touched_twice(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_fixture_premise_is_two_distinct_blame_shas(self):
        """Verify the premise directly, so that if a future change to the
        fixture collapses it back to one sha, this test says so instead of
        the assertions below silently passing for the wrong reason."""
        shas = gitq.blame_shas(self.info["repo"], self.info["path"],
                                self.info["start"], self.info["end"])
        self.assertEqual(set(shas), {self.info["older_sha"], self.info["later_sha"]},
                          shas)

    def test_oldest_of_two_blame_shas_is_reported(self):
        c = next(c for c in self.data["candidates"]
                 if c["path"] == self.info["path"])
        self.assertEqual(c["commented_out_by"]["sha"], self.info["older_sha"])
        self.assertEqual(c["touched_by_commits"], 2)


if __name__ == "__main__":
    unittest.main()
