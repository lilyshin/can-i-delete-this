"""Verdict schema and validator.

The agent writes the verdict; this module refuses the ones that skip
evidence. A grade above `unknown` without a commit reference is a bug,
not a judgement call.
"""

GRADES = ("danger", "conditional", "safe", "unknown")
EVIDENCE_TYPES = ("commit", "pr", "issue", "test", "branch")

# An evidence item's optional `role` says what kind of argument it is, not
# just that it exists. `verdict.py` already tolerated an unlisted `role`
# key silently (any extra key does), so adding validation for it is
# additive: an evidence item that never sets `role` behaves exactly as it
# did before this tuple existed. Once a caller does set it, though, a typo
# must fail loudly here rather than render.py's isolation/lifecycle/risk
# blocks (see that module) silently treating it as absent.
#
# - introduced: the commit that added the code.
# - superseded: the commit that retired the reason the code existed
#   (replaced the mechanism, removed the call site, migrated the
#   behaviour elsewhere). This is the load-bearing evidence for `safe`.
# - guard: a test or check that protects this code. Its presence argues
#   against deleting.
# - reference: something that still mentions the code without calling it
#   (a comment, a doc).
# - risk: a residual hazard that survives the deletion decision.
EVIDENCE_ROLES = ("introduced", "superseded", "guard", "reference", "risk")

ARTIFACT_KINDS = {
    "danger": "keep-comment",
    "conditional": "checklist",
    "safe": "pr-body",
    "unknown": "question",
}


class VerdictError(ValueError):
    """The verdict does not satisfy the schema."""


def validate(v):
    if not isinstance(v, dict):
        raise VerdictError("verdict must be an object")

    grade = v.get("grade")
    if grade not in GRADES:
        raise VerdictError("grade must be one of {}, got {!r}".format(GRADES, grade))

    summary = v.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise VerdictError("summary must be a non-empty string")

    evidence = v.get("evidence")
    if not isinstance(evidence, list):
        raise VerdictError("evidence must be a list")
    for item in evidence:
        if not isinstance(item, dict):
            raise VerdictError("each evidence item must be an object")
        if item.get("type") not in EVIDENCE_TYPES:
            raise VerdictError("evidence type must be one of {}".format(EVIDENCE_TYPES))
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            raise VerdictError("evidence item needs a non-empty string ref")
        if "role" in item and item.get("role") not in EVIDENCE_ROLES:
            raise VerdictError("evidence role must be one of {}, got {!r}".format(
                EVIDENCE_ROLES, item.get("role")))

    if grade != "unknown":
        if not evidence:
            raise VerdictError(
                "grade {!r} requires evidence; use 'unknown' when you have none".format(grade))
        if not any(e["type"] == "commit" for e in evidence):
            raise VerdictError(
                "grade {!r} requires at least one commit reference".format(grade))

    conditions = v.get("conditions", [])
    if not isinstance(conditions, list):
        raise VerdictError("conditions must be a list")
    if grade == "conditional" and not conditions:
        raise VerdictError("grade 'conditional' requires at least one condition")

    artifact = v.get("artifact")
    if not isinstance(artifact, dict):
        raise VerdictError("artifact must be an object")
    expected = ARTIFACT_KINDS[grade]
    if artifact.get("kind") != expected:
        raise VerdictError("grade {!r} expects artifact kind {!r}, got {!r}".format(
            grade, expected, artifact.get("kind")))
    content = artifact.get("content")
    if not isinstance(content, str) or not content.strip():
        raise VerdictError("artifact content must be a non-empty string")


def main():
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Validate a verdict JSON file.")
    ap.add_argument("path")
    args = ap.parse_args()
    with open(args.path, encoding="utf-8") as fh:
        data = json.load(fh)
    try:
        validate(data)
    except VerdictError as exc:
        print("INVALID: {}".format(exc), file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print("INVALID: unexpected error: {}".format(exc), file=sys.stderr)
        raise SystemExit(1)
    print("valid")


if __name__ == "__main__":
    main()
