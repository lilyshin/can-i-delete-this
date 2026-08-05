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
    def test_n1_formatter_by_whitespace_and_breadth(self):
        v = noise.score(commit(subject="chore: apply formatter", files=40),
                        whitespace_only=True, paths=["a.py"] * 40)
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N1")

    def test_n1_formatter_by_subject_alone(self):
        v = noise.score(commit(subject="style: run prettier", files=3),
                        whitespace_only=False, paths=["a.js"])
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N1")

    def test_n3_license_header(self):
        v = noise.score(commit(subject="chore: add copyright headers", files=120),
                        whitespace_only=False, paths=["a.py", "b.py"])
        self.assertEqual(v.category, "N3")

    def test_n6_vendored_paths_only(self):
        v = noise.score(commit(subject="deps: vendor grpc", files=300),
                        whitespace_only=False,
                        paths=["vendor/grpc/a.c", "vendor/grpc/b.c"])
        self.assertEqual(v.category, "N6")

    def test_n9_merge_commit(self):
        v = noise.score(commit(subject="Merge pull request #12", parents=2),
                        whitespace_only=False, paths=["a.py"])
        self.assertEqual(v.category, "N9")

    def test_n2_import_sorting(self):
        v = noise.score(commit(subject="chore: sort imports", files=8),
                        whitespace_only=False, paths=["a.py"], import_ratio=0.95)
        self.assertEqual(v.category, "N2")

    def test_real_hotfix_is_not_noise(self):
        v = noise.score(commit(subject="hotfix: prevent double charge (#4127)", files=1),
                        whitespace_only=False, paths=["payment.py"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_confidence_rises_with_signal_count(self):
        weak = noise.score(commit(subject="style: run prettier", files=2),
                           whitespace_only=False, paths=["a.js"])
        strong = noise.score(commit(subject="style: run prettier", files=80),
                             whitespace_only=True, paths=["a.js"] * 80)
        self.assertGreater(strong.confidence, weak.confidence)


if __name__ == "__main__":
    unittest.main()
