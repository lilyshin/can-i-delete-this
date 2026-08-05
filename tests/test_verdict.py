import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import verdict


def ok_verdict(**over):
    base = {
        "grade": "danger",
        "summary": "Guards against double charge incident #4127.",
        "evidence": [
            {"type": "commit", "ref": "a3f8c21", "note": "introduced during incident"},
            {"type": "test", "ref": "payment_test.py:88", "note": "covers this branch"},
        ],
        "conditions": [],
        "artifact": {"kind": "keep-comment", "content": "// KEEP: ..."},
    }
    base.update(over)
    return base


class TestValidate(unittest.TestCase):
    def test_accepts_well_formed_verdict(self):
        verdict.validate(ok_verdict())

    def test_rejects_unknown_grade_value(self):
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(grade="probably-fine"))

    def test_rejects_graded_verdict_without_evidence(self):
        for grade in ("danger", "conditional", "safe"):
            with self.assertRaises(verdict.VerdictError):
                verdict.validate(ok_verdict(
                    grade=grade, evidence=[],
                    artifact={"kind": verdict.ARTIFACT_KINDS[grade], "content": "x"},
                    conditions=["cond"] if grade == "conditional" else [],
                ))

    def test_rejects_evidence_without_a_commit_reference(self):
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(evidence=[
                {"type": "test", "ref": "payment_test.py:88", "note": "x"},
            ]))

    def test_unknown_grade_may_have_no_evidence(self):
        verdict.validate(ok_verdict(
            grade="unknown", evidence=[],
            artifact={"kind": "question", "content": "Who added this?"},
        ))

    def test_conditional_requires_conditions(self):
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(
                grade="conditional", conditions=[],
                artifact={"kind": "checklist", "content": "x"},
            ))

    def test_artifact_kind_must_match_grade(self):
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(artifact={"kind": "pr-body", "content": "x"}))

    def test_rejects_empty_summary(self):
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(summary="   "))

    def test_rejects_falsy_ref_values(self):
        """Reject ref that is 0, False, or other falsy non-string values."""
        falsy_values = [0, False, None, [], {}]
        for val in falsy_values:
            with self.subTest(ref_value=val):
                with self.assertRaises(verdict.VerdictError):
                    verdict.validate(ok_verdict(evidence=[
                        {"type": "commit", "ref": val, "note": "test"},
                    ]))

    def test_rejects_non_string_ref(self):
        """Reject ref that is a non-string type even if truthy."""
        truthy_values = [42, True, 3.14, [], [0], {}, {"x": 1}]
        for val in truthy_values:
            with self.subTest(ref_value=val):
                with self.assertRaises(verdict.VerdictError):
                    verdict.validate(ok_verdict(evidence=[
                        {"type": "commit", "ref": val, "note": "test"},
                    ]))

    def test_rejects_falsy_content_values(self):
        """Reject artifact content that is 0, False, None, or other falsy values."""
        falsy_values = [0, False, None, [], {}]
        for val in falsy_values:
            with self.subTest(content_value=val):
                with self.assertRaises(verdict.VerdictError):
                    verdict.validate(ok_verdict(artifact={
                        "kind": "keep-comment", "content": val
                    }))

    def test_rejects_non_string_content(self):
        """Reject artifact content that is a non-string type even if truthy."""
        truthy_values = [42, True, 3.14, [], [0], {}, {"x": 1}]
        for val in truthy_values:
            with self.subTest(content_value=val):
                with self.assertRaises(verdict.VerdictError):
                    verdict.validate(ok_verdict(artifact={
                        "kind": "keep-comment", "content": val
                    }))

    def test_rejects_non_string_summary(self):
        """Reject summary that is not a string, even if truthy."""
        non_strings = [42, True, 3.14, None, [], {}, [0], {"x": 1}]
        for val in non_strings:
            with self.subTest(summary_value=val):
                with self.assertRaises(verdict.VerdictError):
                    verdict.validate(ok_verdict(summary=val))

    def test_evidence_item_missing_type_key(self):
        """Reject evidence item that lacks type key."""
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(evidence=[
                {"ref": "abc123", "note": "missing type key"},
            ]))

    def test_evidence_item_with_non_string_type(self):
        """Reject evidence where type is not a string."""
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(evidence=[
                {"type": 42, "ref": "abc123", "note": "type is number"},
            ]))

    def test_artifact_kind_as_non_string(self):
        """Reject artifact.kind that is not a string."""
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(artifact={
                "kind": 42, "content": "test"
            }))

    def test_artifact_kind_mismatch_with_wrong_type(self):
        """Reject when artifact.kind is non-string (can't match expected)."""
        with self.assertRaises(verdict.VerdictError):
            verdict.validate(ok_verdict(
                grade="safe",
                artifact={"kind": None, "content": "test"}
            ))


if __name__ == "__main__":
    unittest.main()
