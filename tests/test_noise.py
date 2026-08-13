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

    # Vocabulary: reported as a hint, never a filter.
    #
    # These commits are all *plausibly* debris, and every one of them is
    # also a shape a real introducing commit takes. The subject alone
    # cannot tell them apart, so it no longer tries: the diff decides, and
    # what the subject claims is handed to the agent as a hint.

    def test_formatter_vocabulary_hints_but_does_not_filter(self):
        v = noise.score(commit(subject="style: run prettier", files=25),
                        whitespace_only=False, paths=["a.js"] * 25)
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")
        self.assertIn("subject matches formatter vocabulary (English)", v.hints)

    def test_license_vocabulary_hints_but_does_not_filter(self):
        v = noise.score(commit(subject="chore: add copyright headers", files=120),
                        whitespace_only=False, paths=["a.py", "b.py"])
        self.assertFalse(v.is_noise)
        self.assertIn("subject mentions license or header (English)", v.hints)

    def test_generated_vocabulary_hints_but_does_not_filter(self):
        v = noise.score(commit(subject="chore: regenerate protobuf stubs", files=30),
                        whitespace_only=False, paths=["api.py"] * 30)
        self.assertFalse(v.is_noise)
        self.assertIn("subject mentions generated code (English)", v.hints)

    def test_move_vocabulary_hints_but_does_not_filter(self):
        """The dangerous one. "refactor: extract ..." over twenty files was
        discarded on the word "extract", and an extraction is exactly where
        a line is often introduced."""
        v = noise.score(commit(subject="refactor: extract net helpers", files=25),
                        whitespace_only=False, paths=["file.py"] * 25)
        self.assertFalse(v.is_noise)
        self.assertIn("subject mentions move or rename (English)", v.hints)

    def test_upgrade_vocabulary_hints_but_does_not_filter(self):
        v = noise.score(commit(subject="chore: upgrade dependencies", files=30),
                        whitespace_only=False,
                        paths=["package.json", "lock.json"] * 15)
        self.assertFalse(v.is_noise)
        self.assertIn("subject mentions upgrade or migration (English)", v.hints)

    def test_squash_pr_shape_hints_but_does_not_filter(self):
        v = noise.score(commit(subject="Add user auth flow (#456)", files=25),
                        whitespace_only=False, paths=["auth.py"] * 25)
        self.assertFalse(v.is_noise)
        self.assertTrue(any("PR-title shaped" in h for h in v.hints))

    def test_typo_vocabulary_hints_but_does_not_filter(self):
        v = noise.score(commit(subject="docs: fix typos in README", files=20),
                        whitespace_only=False, paths=["README.md"] * 20)
        self.assertFalse(v.is_noise)
        self.assertIn("subject mentions typo, comment or docs (English)", v.hints)

    # Evidence: the diff and the commit graph.

    def test_cosmetic_diff_is_noise_whatever_the_subject_says(self):
        v = noise.score(commit(subject="긴급 수정", files=1),
                        whitespace_only=False, paths=["a.py"],
                        diff_lines=(["    x = 'a'"], ['    x = "a"']))
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N1")

    def test_real_change_with_a_formatter_subject_is_not_filtered(self):
        """A commit that claims to be a formatter but changes a value is
        not debris, and the claim does not get to decide."""
        v = noise.score(commit(subject="chore: apply formatter", files=25),
                        whitespace_only=False, paths=["a.py"] * 25,
                        diff_lines=(["timeout = 30"], ["timeout = 5"]))
        self.assertFalse(v.is_noise)

    def test_pure_rename_is_noise(self):
        c = gitq.Commit(
            sha="0" * 40, author="A", author_email="a@example.com",
            date="2023-01-01T00:00:00+00:00", subject="whatever", body="",
            parents_count=1, files_changed=2, insertions=0, deletions=0,
            churn=((0, 0, "old/a.py => new/a.py"), (0, 0, "old/b.py => new/b.py")))
        v = noise.score(c, whitespace_only=False, paths=["new/a.py", "new/b.py"])
        self.assertTrue(v.is_noise)
        self.assertEqual(v.category, "N5")

    def test_rename_carrying_edits_is_not_a_pure_rename(self):
        c = gitq.Commit(
            sha="0" * 40, author="A", author_email="a@example.com",
            date="2023-01-01T00:00:00+00:00", subject="whatever", body="",
            parents_count=1, files_changed=1, insertions=12, deletions=1,
            churn=((12, 1, "old/a.py => new/a.py"),))
        v = noise.score(c, whitespace_only=False, paths=["new/a.py"])
        self.assertFalse(v.is_noise)

    def test_sweep_shape_is_a_hint_not_a_filter(self):
        """Wide and shallow is also the shape of a guard added to twenty
        call sites, which is an answer, not debris."""
        c = gitq.Commit(
            sha="0" * 40, author="A", author_email="a@example.com",
            date="2023-01-01T00:00:00+00:00", subject="add null check", body="",
            parents_count=1, files_changed=25, insertions=25, deletions=0,
            churn=tuple((1, 0, "f{}.py".format(i)) for i in range(25)))
        v = noise.score(c, whitespace_only=False, paths=["f.py"] * 25)
        self.assertFalse(v.is_noise)
        self.assertTrue(any("wide and shallow" in h for h in v.hints))

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

    def test_unfiltered_commit_has_zero_confidence(self):
        v = noise.score(commit(subject="style: run prettier", files=25),
                        whitespace_only=False, paths=["a.js"] * 25)
        self.assertEqual(v.confidence, 0.0)

    def test_strip_comments_in_fix_not_noise(self):
        v = noise.score(commit(subject="fix: strip HTML comments during sanitization", files=1),
                        whitespace_only=False, paths=["sanitizer.py"])
        self.assertFalse(v.is_noise)
        self.assertEqual(v.category, "")

    def test_all_signals_collected_with_multiple_matches(self):
        v = noise.score(commit(subject="chore: refactor imports", files=5, parents=2),
                        whitespace_only=False, paths=["a.py"], import_ratio=0.95)
        self.assertEqual(v.category, "N9")
        self.assertIn("merge commit (parents=2)", v.signals)
        self.assertIn("changes concentrated in import block", v.signals)
        self.assertEqual(len(v.signals), 2)


class TestClassificationIsLanguageIndependent(unittest.TestCase):
    """What replaced the disclosed English-only boundary.

    The old contract was: an English formatter subject over many files
    scores as noise, and the identical commit with a Korean subject does
    not. That gap was not fixable by adding a Korean lexicon, because the
    next repository writes Japanese, or German, or no convention at all.
    It was fixable by not reading the subject: every filtering signal now
    comes from the diff, the paths, or the commit graph.

    See tests/test_noise_language_independence.py for the same guarantee
    proved end to end against real repositories.
    """

    COSMETIC = (["    x = 'a'"], ['    x = "a"'])

    def test_identical_diffs_score_identically_in_any_language(self):
        subjects = [
            "chore: apply formatter across the repo",
            "잡일: 저장소 전체 포맷터 적용",
            "フォーマッタを適用",
            "Formatierung vereinheitlicht",
            "cleanup",
            ".",
        ]
        verdicts = []
        for subject in subjects:
            v = noise.score(commit(subject=subject, files=25),
                            whitespace_only=False, paths=["a.py"] * 25,
                            diff_lines=self.COSMETIC)
            verdicts.append((subject, v.is_noise, v.category))
        for subject, is_noise, category in verdicts:
            self.assertTrue(is_noise, "not filtered under subject {!r}".format(subject))
            self.assertEqual(category, "N1")

    def test_vocabulary_alone_filters_nothing_in_any_language(self):
        for subject in ("chore: apply formatter across the repo",
                        "잡일: 저장소 전체 포맷터 적용"):
            v = noise.score(commit(subject=subject, files=25),
                            whitespace_only=False, paths=["a.py"] * 25)
            self.assertFalse(v.is_noise, subject)
            self.assertEqual(v.signals, (), subject)


class TestCosmeticNormalization(unittest.TestCase):
    """`is_cosmetic` is the one judgement that decides whether a
    token-level formatter is filtered, so its edges are pinned here."""

    def test_quote_flip_is_cosmetic(self):
        self.assertTrue(noise.is_cosmetic(["x = 'a'"], ['x = "a"']))

    def test_indentation_change_is_cosmetic(self):
        self.assertTrue(noise.is_cosmetic(["  x = 1"], ["    x = 1"]))

    def test_trailing_comma_is_cosmetic(self):
        self.assertTrue(noise.is_cosmetic(["    b,"], ["    b"]))

    def test_value_change_is_not_cosmetic(self):
        self.assertFalse(noise.is_cosmetic(["timeout = 30"], ["timeout = 5"]))

    def test_quote_flip_plus_value_change_is_not_cosmetic(self):
        self.assertFalse(noise.is_cosmetic(["x = 'a'"], ['x = "b"']))

    def test_reordering_is_not_cosmetic(self):
        """The multiset of lines is unchanged and the code is not: a set
        comparison would call this cosmetic and discard the commit."""
        self.assertFalse(noise.is_cosmetic(
            ["charge(order)", "log(order)"],
            ["log(order)", "charge(order)"]))

    def test_pure_insertion_is_not_cosmetic(self):
        self.assertFalse(noise.is_cosmetic([], ["x = 1"]))

    def test_pure_deletion_is_not_cosmetic(self):
        self.assertFalse(noise.is_cosmetic(["x = 1"], []))

    def test_unequal_line_counts_are_not_cosmetic(self):
        self.assertFalse(noise.is_cosmetic(
            ["x = 1"], ["x = 1", "y = 2"]))

    def test_empty_diff_is_not_cosmetic(self):
        """An unavailable diff must never read as evidence of debris."""
        self.assertFalse(noise.is_cosmetic([], []))


if __name__ == "__main__":
    unittest.main()
