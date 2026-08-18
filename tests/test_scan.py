import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "skills", "can-i-delete-this", "scripts"))

import gitq  # noqa: E402
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


class TestExcerpt(ScanCase):
    """The block's own text rides along on the candidate, because a scan
    that shares one blame commit across many candidates (a wide merge, in
    the field report this is built from) needs something other than the
    commit line to tell them apart. See scanner.py's `EXCERPT_LINES` and
    `EXCERPT_MAX_CHARS` docstring for the measurement behind this."""

    def test_each_candidate_carries_its_own_excerpt(self):
        for c in self.data["candidates"]:
            self.assertIsInstance(c["excerpt"], list, c["path"])
            self.assertTrue(c["excerpt"], c["path"])

    def test_excerpt_text_is_really_in_the_file(self):
        repo = self.info["repo"]
        for c in self.data["candidates"]:
            text = gitq.run_git(repo, ["show", "HEAD:" + c["path"]])
            for line in c["excerpt"]:
                self.assertIn(line, text, (c["path"], line))


class TestOrderingAndLookFirst(ScanCase):

    def test_oldest_first(self):
        self.assertEqual(self.data["candidates"][0]["path"], "billing.py")
        self.assertEqual(self.data["candidates"][1]["path"], "notes.py")

    def test_look_first_set_by_incident_vocabulary(self):
        by_path = {c["path"]: c for c in self.data["candidates"]}
        self.assertTrue(by_path["billing.py"]["look_first"])
        self.assertFalse(by_path["notes.py"]["look_first"])

    def test_look_first_is_not_a_grade(self):
        """스캔 출력에 등급 단어가 없어야 한다.

        `str(self.data)`가 아니라 `json.dumps`로 검사한다. dict를 str()로 찍으면
        문자열이 홑따옴표로 렌더링되므로 쌍따옴표를 낀 검사 세 건이 영원히
        발화하지 못했고, 후보마다 `"grade": "safe"`를 넣어도 전 테스트가 통과했다.
        실제로 스캔이 내보내는 형식(JSON)을 검사한다."""
        blob = json.dumps(self.data, ensure_ascii=False).lower()
        for word in ("safe to delete", "do not delete",
                     '"grade"', '"safe"', '"danger"', '"conditional"'):
            self.assertNotIn(word, blob)

    def test_no_grade_word_survives_anywhere_in_the_structure(self):
        """위 검사는 등급 단어가 값으로 들어온 경우를 잡는다. 키 이름이나 리스트
        원소로 숨어드는 경우까지 잡으려면 구조를 직접 훑어야 한다."""
        graded = {"safe", "danger", "conditional", "grade"}
        found = []

        def walk(node, where):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(key, str) and key.lower() in graded:
                        found.append("{}.{}".format(where, key))
                    walk(value, "{}.{}".format(where, key))
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    walk(item, "{}[{}]".format(where, i))
            elif isinstance(node, str) and node.strip().lower() in graded:
                found.append("{} = {!r}".format(where, node))

        walk(self.data, "scan")
        self.assertEqual(found, [], found)


class TestLimits(ScanCase):

    def test_scan_scope_is_reported(self):
        limits = self.data["limits"]
        self.assertEqual(limits["files_scanned"], 3)
        self.assertEqual(limits["files_skipped_vendored"], 1)
        self.assertEqual(limits["files_skipped_unsupported"], 1)
        self.assertFalse(limits["candidate_cap_reached"])

    def test_too_large_and_missing_at_head_are_counted_in_limits(self):
        """Neither skip reason is exercised by this fixture, but both keys
        must exist and read 0 (not be absent): a caller reading `limits`
        programmatically cannot see a count that only ever appears as
        conditional free text in `notes`."""
        limits = self.data["limits"]
        self.assertIn("files_skipped_too_large", limits)
        self.assertIn("files_missing_at_head", limits)
        self.assertEqual(limits["files_skipped_too_large"], 0)
        self.assertEqual(limits["files_missing_at_head"], 0)

    def test_block_comment_boundary_is_disclosed(self):
        self.assertTrue(
            any("block comment" in n.lower() for n in self.data["notes"]),
            "the /* */ boundary must be stated, not left for the reader to "
            "discover by missing a block")

    def test_candidate_cap_is_enforced_and_disclosed(self):
        capped = scanmod.scan(self.info["repo"], ".", max_candidates=1, now=NOW)
        self.assertEqual(len(capped["candidates"]), 1)
        self.assertTrue(capped["limits"]["candidate_cap_reached"])

    def test_file_counts_add_up_to_what_git_tracks_even_under_the_cap(self):
        """상한에 걸려 멈추면 남은 파일은 어느 칸에도 세어지지 않은 채 사라졌다.
        그러면 공개하는 총계가 '우리가 어쩌다 닿은 파일 수'가 되고, 상한이 어디서
        걸렸느냐에 따라 총계 자체가 흔들린다. 총계는 언제나 그 경로 아래에서 git이
        추적하는 파일 수와 같아야 한다."""
        tracked = len([l for l in gitq.run_git(self.info["repo"],
                                                ["ls-files", "--", "."]).splitlines()
                       if l.strip()])
        capped = scanmod.scan(self.info["repo"], ".", max_candidates=1, now=NOW)
        limits = capped["limits"]
        self.assertTrue(limits["candidate_cap_reached"])
        counted = (limits["files_scanned"]
                   + limits["files_skipped_unsupported"]
                   + limits["files_skipped_vendored"]
                   + limits["files_skipped_generated"]
                   + limits["files_skipped_too_large"]
                   + limits["files_missing_at_head"]
                   + limits["files_not_reached"])
        self.assertEqual(counted, tracked, limits)
        # The premise: with this cap at least one listed file really is
        # left unopened, so the new counter has something to count.
        self.assertGreater(limits["files_not_reached"], 0, limits)

    def test_unexamined_files_are_disclosed_in_notes(self):
        capped = scanmod.scan(self.info["repo"], ".", max_candidates=1, now=NOW)
        self.assertTrue(
            any("never examined" in n for n in capped["notes"]),
            capped["notes"])

    def test_files_not_reached_is_zero_when_the_cap_is_not_hit(self):
        self.assertEqual(self.data["limits"]["files_not_reached"], 0)


class TestUnsupportedExtensions(ScanCase):

    def test_unsupported_extension_is_counted_not_scanned(self):
        """README.rst contains two code-shaped comment lines (`def
        looks_like_code(x):` and `return x`; `pass` matches none of
        `scanner._CODE_SHAPE`'s patterns). It must be counted as skipped,
        and it must not produce a candidate: a language absent from
        COMMENT_MARKERS is not guessed at."""
        self.assertEqual(self.data["limits"]["files_skipped_unsupported"], 1)
        self.assertNotIn("README.rst",
                          [c["path"] for c in self.data["candidates"]])


class TestOrderingIsReal(unittest.TestCase):
    """`test_oldest_first` above would still pass with `scan()`'s sort key
    deleted entirely: `billing.py` sorts before `notes.py` both
    alphabetically and chronologically, and `ls-files` already lists them
    in that order. This fixture makes the two orders disagree, so only a
    real oldest-first sort can pass."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_ordering_probe(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_chronological_order_wins_over_alphabetical(self):
        paths = [c["path"] for c in self.data["candidates"]]
        # aaa_recent.py sorts first alphabetically (and is what ls-files
        # would list first); zzz_old.py's block is from 2019, three years
        # before aaa_recent.py's 2024 block, so it must lead the results.
        self.assertEqual(paths[0], "zzz_old.py", paths)
        self.assertEqual(paths[1], "aaa_recent.py", paths)


class TestOldestOfSeveralBlameShas(unittest.TestCase):
    """Every block in `build_commented_out` carries exactly one blame sha,
    so `touched_by_commits` is always 1 there and `_oldest`'s "pick the
    oldest of several, report how many" behavior is never exercised. A
    regression returning the newest sha instead of the oldest, or
    hardcoding `touched_by_commits = 1`, would pass every other test in
    this file."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_touched_twice(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_fixture_premise_is_two_distinct_blame_shas(self):
        """Verify the premise directly, so that if a future change to the
        fixture collapses it back to one sha, this test says so instead of
        the assertions below silently passing for the wrong reason."""
        shas = gitq.blame_shas(self.info["repo"], self.info["path"],
                                self.info["start"], self.info["end"])
        self.assertEqual(set(shas), {self.info["older_sha"], self.info["later_sha"]},
                          shas)

    def test_oldest_of_two_blame_shas_is_reported(self):
        c = next(c for c in self.data["candidates"]
                 if c["path"] == self.info["path"])
        self.assertEqual(c["commented_out_by"]["sha"], self.info["older_sha"])
        self.assertEqual(c["touched_by_commits"], 2)


class TestTimezoneSkew(unittest.TestCase):
    """Commit dates are `%aI`, which carries a per-commit UTC offset, so
    text order is not instant order across timezones. Every other fixture
    in `make_fixture_repo` passes offset-free dates, which is why a
    lexicographic sort passed for the wrong reason until now.

    See `build_timezone_skew` for the exact dates: with a string sort the
    chore commit is reported as the one that commented `alpha.py` out, the
    incident commit disappears from the output entirely, `age_days` is
    measured from the wrong commit, and `look_first` goes quiet on the one
    candidate that earned it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_timezone_skew(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_fixture_premise_is_two_shas_whose_orders_disagree(self):
        shas = gitq.blame_shas(self.info["repo"], self.info["alpha_path"],
                                self.info["start"], self.info["end"], rev="HEAD")
        self.assertEqual(set(shas),
                          {self.info["outage_sha"], self.info["chore_sha"]}, shas)

    def test_oldest_by_instant_not_by_text(self):
        c = next(c for c in self.data["candidates"]
                 if c["path"] == self.info["alpha_path"])
        self.assertEqual(c["commented_out_by"]["sha"], self.info["outage_sha"])
        self.assertEqual(c["touched_by_commits"], 2)

    def test_look_first_survives_the_sort(self):
        """The incident commit is the one carrying the urgency vocabulary.
        Picking the chore instead does not merely mislabel the author, it
        turns the hint off on the candidate that most needs it."""
        c = next(c for c in self.data["candidates"]
                 if c["path"] == self.info["alpha_path"])
        self.assertTrue(c["look_first"])

    def test_candidate_order_is_chronological_across_timezones(self):
        paths = [c["path"] for c in self.data["candidates"]]
        # beta.py's date string sorts first; its instant is the newest.
        self.assertEqual(paths[0], self.info["alpha_path"], paths)
        self.assertEqual(paths[1], self.info["beta_path"], paths)


class TestInstantSortKey(unittest.TestCase):
    """A date git cannot be parsed out of must still sort deterministically,
    and must not sort as if it were the oldest thing in the repository."""

    def test_offset_is_honored(self):
        self.assertLess(scanmod._instant("2020-03-02T02:00:00+09:00"),
                         scanmod._instant("2020-03-01T20:00:00-05:00"))

    def test_naive_dates_are_read_as_utc(self):
        self.assertEqual(scanmod._instant("2020-03-01T17:00:00"),
                          scanmod._instant("2020-03-01T17:00:00+00:00"))

    def test_unparseable_dates_sort_last_and_equal_each_other(self):
        unknown = scanmod._instant(None)
        self.assertEqual(unknown, scanmod._instant("not a date"))
        self.assertGreater(unknown, scanmod._instant("2999-12-31T23:59:59+00:00"))


class TestDirtyWorkingTree(unittest.TestCase):
    """The scan reads content from HEAD, so it must blame HEAD too.

    Blaming the working tree with HEAD's line numbers has two failure
    modes, both reproduced here in one repository: an edited line inside
    the range comes back as the all-zeros "not committed yet" sha and used
    to abort the entire run, and a block deleted from the working tree
    used to make `blame -L` answer for different lines, or fail, either
    way disclosing nothing about the block that is really at HEAD."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_commented_out(cls.tmp.name)
        cls.clean = scanmod.scan(cls.info["repo"], ".", now=NOW)

        repo = cls.info["repo"]
        # billing.py: one commented line edited but never committed.
        billing = os.path.join(repo, "billing.py")
        with open(billing, encoding="utf-8") as fh:
            text = fh.read()
        with open(billing, "w", encoding="utf-8") as fh:
            fh.write(text.replace("range(3)", "range(9)"))
        # notes.py: the block deleted outright in the working tree, so
        # HEAD's line numbers point past the end of the file on disk.
        notes = os.path.join(repo, "notes.py")
        with open(notes, "w", encoding="utf-8") as fh:
            fh.write("def helper():\n    return 1\n")

        cls.dirty = scanmod.scan(repo, ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _shape(self, data):
        return [(c["path"], c["start"], c["end"],
                 (c["commented_out_by"] or {}).get("sha"), c["look_first"])
                for c in data["candidates"]]

    def test_the_dirt_is_really_uncommitted(self):
        status = gitq.run_git(self.info["repo"], ["diff", "--name-only"])
        self.assertEqual(sorted(status.split()), ["billing.py", "notes.py"])

    def test_a_dirty_tree_changes_nothing_about_the_answer(self):
        self.assertEqual(self._shape(self.dirty), self._shape(self.clean))

    def test_every_candidate_still_carries_its_commit(self):
        for c in self.dirty["candidates"]:
            self.assertIsNotNone(c["commented_out_by"], c["path"])

    def test_the_incident_commit_is_still_the_answer_for_billing(self):
        c = next(c for c in self.dirty["candidates"] if c["path"] == "billing.py")
        self.assertEqual(c["commented_out_by"]["sha"], self.info["outage_sha"])


class TestUnusableBlameSha(ScanCase):
    """A sha blame reports but `commit_meta` cannot read costs one
    candidate its facts, never the run.

    The lookup used to sit outside the only try/except in the loop, so a
    single unreadable sha raised through `main`, which printed one line and
    exited 1 having emitted nothing: every other file's candidates were
    thrown away because one file was unusable. Forced here with a sha that
    is well-formed and absent from the repository, which is deterministic
    in a way a race against a real dirty tree is not."""

    ABSENT_SHA = "f" * 40

    def _scan_with_one_bad_sha(self):
        real = gitq.blame_shas
        first = []

        def fake(repo, path, start, end, rev=None):
            if not first:
                first.append(path)
            if path == first[0]:
                return [self.ABSENT_SHA]
            return real(repo, path, start, end, rev=rev)

        with mock.patch.object(scanmod.gitq, "blame_shas", side_effect=fake):
            return scanmod.scan(self.info["repo"], ".", now=NOW), first[0]

    def test_the_run_survives_and_keeps_every_candidate(self):
        data, poisoned = self._scan_with_one_bad_sha()
        self.assertEqual(len(data["candidates"]), len(self.data["candidates"]))
        # Same candidates, though the one with no facts now sorts last.
        self.assertEqual(sorted(c["path"] for c in data["candidates"]),
                          sorted(c["path"] for c in self.data["candidates"]))
        self.assertIn(poisoned, [c["path"] for c in data["candidates"]])

    def test_the_affected_candidate_reports_no_commit_and_says_so(self):
        data, poisoned = self._scan_with_one_bad_sha()
        hit = next(c for c in data["candidates"] if c["path"] == poisoned)
        self.assertIsNone(hit["commented_out_by"])
        self.assertEqual(hit["touched_by_commits"], 0)
        self.assertFalse(hit["look_first"])
        self.assertTrue(any(poisoned in n and "blame failed" in n
                            for n in data["notes"]), data["notes"])

    def test_the_other_candidates_keep_their_facts(self):
        data, poisoned = self._scan_with_one_bad_sha()
        others = [c for c in data["candidates"] if c["path"] != poisoned]
        self.assertTrue(others)
        for c in others:
            self.assertIsNotNone(c["commented_out_by"], c["path"])


class TestBlockComment(unittest.TestCase):
    """One `/* ... */` block of dead code and one `/** ... */` KDoc block in
    the same Kotlin file. Only the dead code is a candidate: the doc
    comment is discarded whole regardless of how code-shaped its text
    looks (see scanner.py's module docstring)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.info = make_fixture_repo.build_block_comment(cls.tmp.name)
        cls.data = scanmod.scan(cls.info["repo"], ".", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exactly_one_candidate(self):
        paths = [(c["path"], c["start"], c["end"]) for c in self.data["candidates"]]
        self.assertEqual(len(self.data["candidates"]), 1, paths)

    def test_the_candidate_is_the_dead_code_not_the_kdoc(self):
        """Checked against every candidate the scan returned, not just the
        first: the KDoc body is deliberately as code-shaped as the dead
        code (see `build_block_comment`'s docstring), so if the `/**`
        exclusion were ever weakened the KDoc's own range (9-14) would
        surface as a second candidate. Indexing `candidates[0]` alone would
        miss that, since the oldest-first sort still puts the dead code
        first when both share one commit."""
        paths = [(c["path"], c["start"], c["end"]) for c in self.data["candidates"]]
        self.assertIn(("Billing.kt", 2, 7), paths, paths)
        self.assertNotIn(("Billing.kt", 9, 14), paths, paths)

    def test_the_candidate_carries_its_own_excerpt(self):
        c = self.data["candidates"][0]
        self.assertTrue(c["excerpt"], c)
        text = gitq.run_git(self.info["repo"], ["show", "HEAD:" + c["path"]])
        for line in c["excerpt"]:
            self.assertIn(line, text)

    def test_the_excerpt_is_the_dead_code_not_the_kdoc(self):
        """The fixture's KDoc body (`legacyDiscount`) is deliberately just as
        code-shaped as the real dead code (`oldCharge`); see
        `build_block_comment`'s docstring. The only thing that can be
        keeping it out of every candidate's excerpt is the `/**` exclusion
        itself, not a weaker signal like prose wording or a length gate.
        Checked across every candidate, not just the first, for the same
        reason as the test above."""
        joined = " ".join(line for c in self.data["candidates"]
                          for line in (c.get("excerpt") or []))
        self.assertNotIn("legacyDiscount", joined)

    def test_the_commenting_commit_is_carried(self):
        c = self.data["candidates"][0]
        self.assertEqual(c["commented_out_by"]["sha"], self.info["sha"])


if __name__ == "__main__":
    unittest.main()
