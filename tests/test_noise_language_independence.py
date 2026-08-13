"""The commit subject is a description of a change, in whatever language
its author speaks, under whatever convention their repository uses. It is
not the change. These tests pin the requirement that noise classification
reads the change.

Every case below builds the *same* repository as `build_f1` (a repo-wide
quote-style flip burying a real hotfix) and varies only the wording of the
commit subjects. A classifier that reads the diff returns the same verdict
for all of them.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "skills", "can-i-delete-this", "scripts"))

import make_fixture_repo  # noqa: E402
import gitq  # noqa: E402
import noise  # noqa: E402
import trace as tracer  # noqa: E402


# (label, noise-commit subject, real-commit subject)
SUBJECT_VARIANTS = [
    ("english", "chore: apply formatter", "hotfix: prevent double charge (#4127)"),
    ("korean", "chore: 포맷터 일괄 적용", "긴급수정: 결제 중복 승인 방지 (#4127)"),
    ("japanese", "フォーマッタを適用", "緊急修正: 二重課金を防止"),
    ("german", "Formatierung vereinheitlicht", "Notfallkorrektur: doppelte Belastung verhindert"),
    ("no convention", "cleanup", "fix double charge"),
    ("empty-ish subject", ".", "guard"),
]


def _score(repo, sha, path):
    """Score a commit exactly as trace.py does, path-scoped included."""
    commit = gitq.commit_meta(repo, sha)
    return noise.score(
        commit,
        whitespace_only=gitq.is_whitespace_only(repo, sha),
        paths=gitq.changed_paths(repo, sha),
        diff_lines=gitq.diff_lines(repo, sha, path),
    )


class TestFormatterDetectedWithoutVocabulary(unittest.TestCase):
    """A quote-style sweep is debris because of its diff, not its wording."""

    def test_every_subject_variant_scores_the_sweep_as_noise(self):
        for label, noise_subject, real_subject in SUBJECT_VARIANTS:
            with self.subTest(subject=label):
                with tempfile.TemporaryDirectory() as tmp:
                    info = make_fixture_repo.build_f1(
                        tmp, noise_subject=noise_subject,
                        real_subject=real_subject,
                        name="f1_" + label.replace(" ", "_"))
                    v = _score(info["repo"], info["noise_sha"], info["path"])
                    self.assertTrue(
                        v.is_noise,
                        "{!r} sweeps 25 files flipping quote style and is "
                        "debris regardless of how its subject is worded; "
                        "signals={}".format(noise_subject, v.signals))

    def test_the_real_fix_is_never_scored_as_noise(self):
        """The asymmetry that matters: discarding the real introducing
        commit is unrecoverable, so no wording may cause it."""
        for label, noise_subject, real_subject in SUBJECT_VARIANTS:
            with self.subTest(subject=label):
                with tempfile.TemporaryDirectory() as tmp:
                    info = make_fixture_repo.build_f1(
                        tmp, noise_subject=noise_subject,
                        real_subject=real_subject,
                        name="f1_real_" + label.replace(" ", "_"))
                    v = _score(info["repo"], info["real_sha"], info["path"])
                    self.assertFalse(
                        v.is_noise,
                        "the real introducing commit was discarded as noise "
                        "under subject {!r}; signals={}".format(
                            real_subject, v.signals))


class TestTracerFindsTheRealCommitInAnyLanguage(unittest.TestCase):
    """End to end: the ranked candidate list must not depend on wording."""

    def test_real_commit_survives_and_sweep_is_filtered(self):
        for label, noise_subject, real_subject in SUBJECT_VARIANTS:
            with self.subTest(subject=label):
                with tempfile.TemporaryDirectory() as tmp:
                    info = make_fixture_repo.build_f1(
                        tmp, noise_subject=noise_subject,
                        real_subject=real_subject,
                        name="f1_trace_" + label.replace(" ", "_"))
                    data = tracer.trace(
                        info["repo"], info["path"], info["line"], info["line"])
                    shas = [c["sha"] for c in data["introduction_candidates"]]
                    self.assertIn(
                        info["real_sha"], shas,
                        "the real introducing commit is missing from the "
                        "candidates under subject {!r}".format(real_subject))
                    self.assertNotIn(
                        info["noise_sha"], shas,
                        "the quote-style sweep reached the candidate list "
                        "under subject {!r}".format(noise_subject))


class TestVocabularyNeverFilters(unittest.TestCase):
    """English vocabulary may hint, but must never remove a candidate.

    Today a 20-file commit saying "refactor: extract net helpers" is
    discarded on the strength of the word "extract" alone. If that commit
    is the real introduction, the answer is gone and nothing downstream
    can recover it.
    """

    def _commit(self, subject, files=25):
        return gitq.Commit(
            sha="a" * 40, author="A", author_email="a@example.com",
            date="2024-01-01T00:00:00+00:00", subject=subject, body="",
            parents_count=1, files_changed=files, insertions=400,
            deletions=380)

    def test_english_keyword_alone_does_not_mark_noise(self):
        for subject in ("refactor: extract net helpers",
                        "chore: apply formatter",
                        "docs: fix typo in comments",
                        "build: bump deps and migrate to v2"):
            with self.subTest(subject=subject):
                v = noise.score(self._commit(subject), whitespace_only=False,
                                paths=["src/a.py"] * 25)
                self.assertFalse(
                    v.is_noise,
                    "{!r} was filtered out on vocabulary alone, with no "
                    "structural or diff-shape signal".format(subject))

    def test_keyword_match_is_still_reported_as_a_hint(self):
        v = noise.score(self._commit("chore: apply formatter"),
                        whitespace_only=False, paths=["src/a.py"] * 25)
        self.assertTrue(
            v.hints,
            "the vocabulary match should still be reported for the agent "
            "to weigh, just not acted on as a filter")


if __name__ == "__main__":
    unittest.main()
