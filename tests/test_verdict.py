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


if __name__ == "__main__":
    unittest.main()
