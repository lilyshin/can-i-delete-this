"""Every candidate carries its commit body, bounded and disclosed.

The subject alone rarely says why code exists; `SKILL.md` step 5 sends the
agent to the body, the PR link and the tests for intent. The body is already
read by `gitq.commit_meta` for every candidate, so withholding it from the
JSON only bought the agent an extra `git show` per commit it wanted to
understand.

It is bounded because it is unbounded upstream: measured across 60 commits
of a real 20,000-commit repository, bodies run to a median of 280 characters
and a maximum of 3,725, and a capped trace can hold 200 candidates. A
truncated body says so, so the agent knows to run `git show` rather than
believing it read the whole thing.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "skills", "can-i-delete-this", "scripts"))

import make_fixture_repo  # noqa: E402
import trace as tracer  # noqa: E402


class TestBodyIsCarried(unittest.TestCase):

    def test_candidate_carries_the_commit_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_body_message(tmp)
            data = tracer.trace(info["repo"], info["path"], info["line"],
                                 info["line"])
            cand = next(c for c in data["introduction_candidates"]
                        if c["sha"] == info["real_sha"])
            self.assertIn("Customers were charged twice", cand["body"])
            self.assertFalse(cand["body_truncated"])

    def test_blame_candidate_carries_the_body_too(self):
        """The commit blame reports is the one an agent most needs to judge,
        so it must not be the one shape missing its own message."""
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_body_message(tmp)
            data = tracer.trace(info["repo"], info["path"], info["line"],
                                 info["line"])
            self.assertTrue(data["blame_candidates"])
            for b in data["blame_candidates"]:
                self.assertIn("body", b)
                self.assertIn("body_truncated", b)

    def test_a_commit_with_no_body_gets_an_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_f1(tmp)
            data = tracer.trace(info["repo"], info["path"], info["line"],
                                 info["line"])
            for c in data["introduction_candidates"]:
                self.assertEqual(c["body"], "")
                self.assertFalse(c["body_truncated"])


class TestBodyIsBounded(unittest.TestCase):

    def test_a_long_body_is_cut_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = make_fixture_repo.build_body_message(
                tmp, body="x" * 5000, name="long_body")
            data = tracer.trace(info["repo"], info["path"], info["line"],
                                 info["line"])
            cand = next(c for c in data["introduction_candidates"]
                        if c["sha"] == info["real_sha"])
            self.assertEqual(len(cand["body"]), tracer._BODY_LIMIT)
            self.assertTrue(
                cand["body_truncated"],
                "a cut body must be disclosed, or an agent will believe it "
                "read the whole message")


if __name__ == "__main__":
    unittest.main()
