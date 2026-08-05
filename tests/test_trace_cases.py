import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import make_fixture_repo
import trace as tracer


class CaseMixin:
    builder = None

    def build(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        info = getattr(make_fixture_repo, self.builder)(self.tmp.name)
        result = tracer.trace(info["repo"], info["path"], info["line"], info["line"])
        return info, result

    def assert_real_commit_found(self, info, result):
        shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertIn(info["real_sha"], shas,
                      "real introducing commit missing from candidates")


class TestF2Rename(CaseMixin, unittest.TestCase):
    builder = "build_f2"

    def test_finds_commit_across_rename(self):
        info, result = self.build()
        self.assert_real_commit_found(info, result)


class TestF3Move(CaseMixin, unittest.TestCase):
    builder = "build_f3"

    def test_finds_commit_in_origin_file(self):
        info, result = self.build()
        self.assert_real_commit_found(info, result)


class TestF5RevertChain(CaseMixin, unittest.TestCase):
    builder = "build_f5"

    def test_revert_chain_is_reported(self):
        info, result = self.build()
        subjects = [c["subject"] for c in result["revert_chain"]]
        self.assertTrue(any("Revert" in s or "reapply" in s for s in subjects),
                        "revert chain must surface for F5")

    def test_both_introduction_and_reintroduction_are_candidates(self):
        info, result = self.build()
        shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertIn(info["first_sha"], shas)
        self.assertIn(info["reintro_sha"], shas)


class TestF6Vendor(CaseMixin, unittest.TestCase):
    builder = "build_f6"

    def test_vendor_commit_is_not_a_candidate(self):
        info, result = self.build()
        shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertNotIn(info["vendor_sha"], shas)
        self.assert_real_commit_found(info, result)


class TestF7Merge(CaseMixin, unittest.TestCase):
    builder = "build_f7"

    def test_merge_commit_is_filtered(self):
        info, result = self.build()
        shas = [c["sha"] for c in result["introduction_candidates"]]
        self.assertNotIn(info["merge_sha"], shas)
        self.assert_real_commit_found(info, result)


class TestF4Squash(CaseMixin, unittest.TestCase):
    builder = "build_f4"

    def test_reports_why_it_came_up_empty(self):
        info, result = self.build()
        shas = [c["sha"] for c in result["introduction_candidates"]]
        if info["real_sha"] in shas:
            self.skipTest("squash commit survived filtering; nothing to explain")
        self.assertIn("pickaxe", " ".join(result["notes"]),
                      "when all candidates are filtered, notes must explain")

    def test_pr_number_is_recoverable_from_subject(self):
        info, result = self.build()
        subjects = [b["subject"] for b in result["blame_candidates"]]
        self.assertTrue(any("(#2211)" in s for s in subjects))


if __name__ == "__main__":
    unittest.main()
