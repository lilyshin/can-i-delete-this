import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "skills", "can-i-delete-this", "scripts"))

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
        """README.rst contains three code-shaped comment lines. It must be
        counted as skipped, and it must not produce a candidate: a language
        absent from COMMENT_MARKERS is not guessed at."""
        self.assertEqual(self.data["limits"]["files_skipped_unsupported"], 1)
        self.assertNotIn("README.rst",
                          [c["path"] for c in self.data["candidates"]])


if __name__ == "__main__":
    unittest.main()
