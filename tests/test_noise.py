import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import gitq
import noise


def commit(subject="chore: tidy", files=1, body="", parents=1):
    return gitq.Commit(
        sha="0" * 40, author="A", author_email="a@example.com",
        date="2023-01-01T00:00:00+00:00", subject=subject, body=body,
        parents_count=parents, files_changed=files, insertions=10, deletions=10,
    )


class TestNoiseScoring(unittest.TestCase):
    # Stage 1: Structural signals (high confidence, standalone)

    def test_n1_whitespace_only_is_noise(self):
        v = noise.score(commit(subject="chore: apply formatter", files=40),
                        whitespace_only=True, paths=["a.py"] * 40)
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N1")
        self.assertGreater(v.confidence, 0.9)

    def test_n2_high_import_ratio_is_noise(self):
        v = noise.score(commit(subject="chore: refactor", files=5),
                        whitespace_only=False, paths=["a.py"], import_ratio=0.85)
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N2")
        self.assertGreater(v.confidence, 0.9)

    def test_n6_vendored_paths_only(self):
        v = noise.score(commit(subject="deps: vendor grpc", files=300),
                        whitespace_only=False,
                        paths=["vendor/grpc/a.c", "vendor/grpc/b.c"])
        self.assertEqual(v.category, "N6")
        self.assertGreater(v.confidence, 0.9)

    def test_n9_merge_commit(self):
        v = noise.score(commit(subject="Merge pull request #12", parents=2),
                        whitespace_only=False, paths=["a.py"])
        self.assertEqual(v.category, "N9")
        self.assertGreater(v.confidence, 0.9)

    def test_n9_priority_over_whitespace(self):
        v = noise.score(commit(subject="Merge pull request #12", parents=2),
                        whitespace_only=True, paths=["a.py"])
        self.assertEqual(v.category, "N9")

    # Stage 2: Keywords + breadth (lower confidence, require files >= 20)

    def test_n1_formatter_keyword_with_breadth(self):
        v = noise.score(commit(subject="style: run prettier", files=25),
                        whitespace_only=False, paths=["a.js"] * 25)
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N1")
        self.assertGreater(v.confidence, 0.6)

    def test_n3_license_header_with_breadth(self):
        v = noise.score(commit(subject="chore: add copyright headers", files=120),
                        whitespace_only=False, paths=["a.py", "b.py"])
        self.assertEqual(v.category, "N3")
        self.assertGreater(v.confidence, 0.6)

    def test_n7_generated_code_with_breadth(self):
        v = noise.score(commit(subject="chore: regenerate protobuf stubs", files=30),
                        whitespace_only=False, paths=["api.py"] * 30)
        self.assertEqual(v.category, "N7")

    def test_n7_generated_hints_in_paths(self):
        v = noise.score(commit(subject="chore: rebuild", files=10),
                        whitespace_only=False, paths=["a_pb2.py", "b_pb2.py"])
        self.assertEqual(v.category, "N7")
        self.assertGreater(v.confidence, 0.9)

    def test_n5_move_rename_with_breadth(self):
        v = noise.score(commit(subject="refactor: rename module for clarity", files=25),
                        whitespace_only=False, paths=["file.py"] * 25)
        self.assertEqual(v.category, "N5")

    def test_n8_upgrade_with_breadth(self):
        v = noise.score(commit(subject="chore: upgrade dependencies", files=30),
                        whitespace_only=False, paths=["package.json", "lock.json"] * 15)
        self.assertEqual(v.category, "N8")

    def test_n10_squash_pr_with_breadth(self):
        v = noise.score(commit(subject="Add user auth flow (#456)", files=25),
                        whitespace_only=False, paths=["auth.py"] * 25)
        self.assertEqual(v.category, "N10")

    def test_n11_typo_docs_with_breadth(self):
        v = noise.score(commit(subject="docs: fix typos in README", files=20),
                        whitespace_only=False, paths=["README.md"] * 20)
        self.assertEqual(v.category, "N11")

    # Keywords alone (no breadth): should NOT be noise

    def test_formatter_keyword_alone_is_not_noise(self):
        v = noise.score(commit(subject="style: run prettier", files=3),
                        whitespace_only=False, paths=["a.js"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_real_hotfix_is_not_noise(self):
        v = noise.score(commit(subject="hotfix: prevent double charge (#4127)", files=1),
                        whitespace_only=False, paths=["payment.py"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    # Regression tests for false positives found by reviewer

    def test_real_multifile_fix_not_noise(self):
        v = noise.score(commit(subject="fix: handle currency rounding correctly in multi-region checkout flow", files=22),
                        whitespace_only=False, paths=["checkout.py"] * 22)
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_header_in_bug_fix_not_noise(self):
        v = noise.score(commit(subject="fix: correct HTTP header parsing bug in gateway", files=1),
                        whitespace_only=False, paths=["gateway.py"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_docs_in_feature_not_noise(self):
        v = noise.score(commit(subject="docs: add OAuth troubleshooting guide", files=2),
                        whitespace_only=False, paths=["guide.md", "index.md"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_extract_in_feature_not_noise(self):
        v = noise.score(commit(subject="feat: extract user metadata from JWT claims", files=1),
                        whitespace_only=False, paths=["auth.py"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_bump_in_fix_not_noise(self):
        v = noise.score(commit(subject="fix: bump connection pool size to handle burst load", files=1),
                        whitespace_only=False, paths=["pool.py"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_confidence_stage1_higher_than_stage2(self):
        stage1 = noise.score(commit(subject="chore: refactor", files=5),
                             whitespace_only=True, paths=["a.py"])
        stage2 = noise.score(commit(subject="style: run prettier", files=25),
                             whitespace_only=False, paths=["a.js"] * 25)
        self.assertGreater(stage1.confidence, stage2.confidence)


if __name__ == "__main__":
    unittest.main()
