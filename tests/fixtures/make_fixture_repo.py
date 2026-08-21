"""Build git repositories with booby-trapped history for regression tests.

This module writes git history and runs git commands, which is allowed for test
fixture builders. Read-only git access is enforced in a separate module.
"""

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ENV = {
    "GIT_AUTHOR_NAME": "Fixture Author",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture Author",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
}


def _days_ago(days: int) -> str:
    """A commit date `days` days before "now".

    Not used by the fixture builders below: their commit dates are fixed
    (trace()'s default `since` is None, so there is no rolling window for
    a fixed historical date to age out of, and fixed dates keep those
    tests deterministic). This helper remains for tests that specifically
    exercise an explicit, relative `since` cutoff (e.g. TestLineHistory in
    test_gitq.py), where "N days before whenever this runs" is exactly
    the relationship being tested.
    """
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def _git(repo: Path, *args: str, date: str = None) -> str:
    env = dict(os.environ)
    env.update(ENV)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        check=True, env=env,
    ).stdout.strip()


def _init(dest: str, name: str) -> Path:
    repo = Path(dest) / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    return repo


def _commit(repo: Path, message: str, date: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, date=date)
    return _git(repo, "rev-parse", "HEAD")


def build_f1(dest: str, *, noise_subject: str = "chore: apply formatter",
             real_subject: str = "hotfix: prevent double charge (#4127)",
             name: str = "f1") -> dict:
    """N1: a repo-wide formatter commit flips string-quote style, burying
    the real author of the target line.

    `noise_subject`, `real_subject` and `name` exist so the identical
    repository can be rebuilt with commit subjects in another language,
    or with no recognizable vocabulary at all. The diff is what makes
    this commit debris; the subject is a description of it that may be
    absent, misleading, or in any human language. See
    `tests/test_noise_language_independence.py`.

    `git blame -w` only ignores whitespace, so a formatter that merely
    reindents can be seen through by blame on its own, with nothing left
    for noise-scoring or the pickaxe fallback to do. Real formatters
    (black, prettier, ...) also rewrite tokens, e.g. unifying quote
    characters. That is a content change, not a whitespace change, so it
    survives `git blame -w -C -C -C` (the exact invocation
    gitq.blame_shas uses, including copy/move detection). The formatter
    commit also touches enough files to clear noise.py's
    BREADTH_THRESHOLD, so its "chore: apply formatter" subject is enough
    for noise.score to flag it under N1 even though the diff is no longer
    whitespace-only.

    Dates are fixed (not relative to "now"): trace()'s default `since` is
    None (no time bound at all -- an archaeology tool for old code cannot
    default to ignoring old code), so there is no rolling window for a
    fixed historical date to age out of, and fixed dates keep this test
    deterministic across runs.
    """
    repo = _init(dest, name)
    target = repo / "payment.py"
    extra_files = [repo / "file_{:02d}.py".format(i) for i in range(24)]

    # The base line deliberately avoids the word "return": it is one of the
    # target line's pickaxe needles (see _needles in trace.py). Since
    # trace()'s default `since` is None, pickaxe searches full history by
    # default with no date cutoff, so if this base commit also introduced
    # "return" it would be a second, older, non-noise pickaxe hit that
    # outranks the real fix by date -- this is independent of whether
    # dates are fixed or relative. It is also kept byte-identical across
    # every later commit so the guard clause is a pure insertion above it,
    # not a rewrite of it; git's line-history (-L) walks back through
    # rewritten lines, and this fixture wants the real fix to be the
    # line's true origin.
    target.write_text(
        "def charge(order):\n"
        "    order.mark_processed()\n"
    )
    for f in extra_files:
        f.write_text("x = 'value_{}'\n".format(f.stem))
    _commit(repo, "feat: add charge", "2019-01-05T10:00:00")

    # The real introduction: a guard added during an incident.
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return {'status': 'duplicate'}\n"
        "    order.mark_processed()\n"
    )
    real_sha = _commit(repo, real_subject, "2019-11-08T02:14:00")

    # Noise: a repo-wide formatter flips single quotes to double quotes
    # across every file, including the target line. Token-level change,
    # not whitespace, and wide enough to clear the breadth threshold.
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        '        return {"status": "duplicate"}\n'
        "    order.mark_processed()\n"
    )
    for f in extra_files:
        f.write_text('x = "value_{}"\n'.format(f.stem))
    noise_sha = _commit(repo, noise_subject, "2023-06-01T09:00:00")

    return {
        "repo": str(repo),
        "path": "payment.py",
        "line": 3,  # `return {"status": "duplicate"}` (post-formatter)
        "real_sha": real_sha,
        "noise_sha": noise_sha,
    }


def build_revert_merge_noise(dest: str) -> dict:
    """A GitHub-style revert folded back in by an actual merge commit
    (2 parents), reachable through line-history but not through blame or
    pickaxe for the target line.

    Not F5: F5 (revert-then-reintroduce) is a separate, later fixture.

    Regression fixture for the requirement that revert_chain survive
    noise filtering, without leaning on blame (a real merge commit's own
    sha is not attainable through gitq.pickaxe(): git suppresses merge
    diffs from `-S` unless --first-parent/-m/--full-history is added,
    which gitq.pickaxe() does not do). Two branches independently touch
    the same line after diverging, so merging them conflicts and must be
    resolved by hand; git blame would normally attribute a genuinely
    resolved conflict line to the merge commit itself, but one further
    small commit lands after the merge and touches that same line again,
    so blame's current attribution moves past the merge commit while
    line-history's full lineage still walks through it. noise.score
    classifies the merge N9 (parents_count=2) unconditionally, so add()
    would have discarded it before revert_chain ever saw it, unless
    revert_chain is collected from every sha encountered along a search
    path regardless of its noise verdict.
    """
    repo = _init(dest, "revert_merge_noise")
    target = repo / "feature.py"

    target.write_text("ENABLED_FEATURES = []\n")
    _commit(repo, "chore: base", "2020-01-01T10:00:00")

    target.write_text('ENABLED_FEATURES = ["quota_guard_v2"]\n')
    _commit(repo, "feat: real change", "2020-03-01T10:00:00")

    _git(repo, "checkout", "-q", "-b", "revert-branch")
    target.write_text("ENABLED_FEATURES = []\n")
    _commit(repo, 'Revert "feat: real change"', "2020-05-01T10:00:00")

    _git(repo, "checkout", "-q", "main")
    target.write_text('ENABLED_FEATURES = ["quota_guard_v2", "extra_flag"]\n')
    _commit(repo, "chore: unrelated tweak", "2020-04-15T10:00:00")

    # This merge conflicts by construction: main and revert-branch each
    # changed the same line differently since diverging. Let it fail, then
    # resolve by hand and finish the commit through the usual helper.
    env = dict(os.environ)
    env.update(ENV)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(
        ["git", "merge", "--no-ff", "-q", "-m",
         'Revert "feat: real change" (#9)', "revert-branch"],
        cwd=repo, capture_output=True, text=True, env=env,
    )
    target.write_text('ENABLED_FEATURES = ["extra_flag"]\n')
    revert_sha = _commit(repo, 'Revert "feat: real change" (#9)', "2020-05-02T10:00:00")

    # One further, unrelated small edit after the merge so blame's current
    # attribution for line 1 moves past the merge commit, while line-history
    # still walks through it as part of the line's full lineage.
    target.write_text('ENABLED_FEATURES = ["extra_flag", "cosmetic"]\n')
    _commit(repo, "chore: cosmetic tweak", "2020-06-01T10:00:00")

    return {
        "repo": str(repo),
        "path": "feature.py",
        "line": 1,
        "revert_sha": revert_sha,
    }


def build_f2(dest: str) -> dict:
    """N4: the file is renamed after the line was introduced, and the rename
    commit also adds enough unrelated content that git's own similarity-based
    rename detection no longer recognizes it as a rename.

    A plain `git mv` with no other change in the same commit is NOT a trap:
    `git blame` (even with zero flags, no -C needed) follows a pure rename of
    a file on its own, because the default diff machinery it relies on
    detects a 100%-similarity rename unconditionally. Verified empirically:
    blame_shas on a plain-rename variant of this fixture returns real_sha
    directly, so a test built on that construction would pass for a reason
    that has nothing to do with rename handling.

    Real-world renames rarely arrive alone, though; they routinely land in
    the same commit as other reorganizing edits (e.g. new helpers added while
    the module is folded into another one). That is what this fixture
    reproduces: the rename commit also inserts six unrelated helper functions
    (12 lines) ahead of the moved code. Against the original 4-line file that
    drops post-rename similarity below the threshold `git blame -w -C -C -C`
    (gitq.blame_shas' exact invocation) needs to keep following the file's
    identity across the rename, so blame misattributes the target line to the
    rename commit. Empirically confirmed: 3-4 helper functions still let
    blame follow the rename; 5 or more break it, so 6 is used for margin.

    trace()'s existing pickaxe fallback already recovers real_sha
    here without any further tracer change: `-S` searches full history for a
    string's introduction regardless of which path it lived in, so the
    needle drawn from the target line ("order.total_with_vat") finds the
    real commit even though blame cannot. No --follow addition was needed for
    this fixture; see the report for the empirical check.

    checkout/mv/merge are write operations, only permitted here because this
    is the test fixture generator, not the read-only production git access
    path (that guard lives in gitq.run_git and is exercised by test_gitq.py).
    """
    repo = _init(dest, "f2")
    old = repo / "payment.py"
    old.write_text("def charge(order):\n    return order.total\n")
    _commit(repo, "feat: add charge", "2020-01-05T10:00:00")

    old.write_text(
        "def charge(order):\n"
        "    if order.region == 'EU':\n"
        "        return order.total_with_vat\n"
        "    return order.total\n"
    )
    real_sha = _commit(repo, "feat: apply EU VAT (#901)", "2020-04-11T10:00:00")

    new = repo / "billing_payment.py"
    _git(repo, "mv", "payment.py", "billing_payment.py")
    helpers = "".join("def helper_{}():\n    pass\n".format(i) for i in range(6))
    new.write_text(helpers + new.read_text())
    rename_sha = _commit(repo, "refactor: move payment into billing", "2022-02-02T10:00:00")

    return {
        "repo": str(repo), "path": "billing_payment.py", "old_path": "payment.py",
        "line": 15, "real_sha": real_sha, "noise_sha": rename_sha,
    }


def build_f3(dest: str) -> dict:
    """N5: a function moves to a different file, while the origin file is
    left behind with unrelated content (not deleted).

    This is a genuine trap, confirmed empirically: `git blame -w -C -C -C`
    (gitq.blame_shas' exact invocation) still misattributes the target line
    to move_sha. -C is documented to detect lines "moved or copied from
    other files that were modified in the same commit", which is exactly
    what happens here (util.py is modified, not removed, in the same commit
    that creates net.py), yet blame does not follow it back to real_sha.
    A second experiment isolated why: replacing `origin.write_text("# moved
    to net.py\n")` with an actual `git rm util.py` (so the source file is
    deleted rather than merely emptied) DOES let blame resolve to real_sha,
    but that is because a fully deleted-and-recreated identical file is
    treated as a plain rename (the same mechanism that made the naive
    version of F2 not a trap), not because -C's cross-file copy detection
    kicked in. With the origin file merely emptied to a comment, as this
    fixture does, that plain-rename shortcut is unavailable and -C's copy
    detection does not pick up the slack, so the trap holds.

    trace()'s existing pickaxe fallback already recovers real_sha
    here: pickaxe runs unrestricted by path, so a needle drawn from the
    moved function ("retry_once") finds its true origin commit regardless of
    which file it lived in at the time. No tracer change was needed for this
    fixture either.
    """
    repo = _init(dest, "f3")
    origin = repo / "util.py"
    origin.write_text(
        "def retry_once(fn):\n"
        "    try:\n"
        "        return fn()\n"
        "    except TimeoutError:\n"
        "        return fn()\n"
    )
    real_sha = _commit(repo, "fix: retry once on flaky timeout (#77)",
                       "2021-03-03T10:00:00")

    origin.write_text("# moved to net.py\n")
    moved = repo / "net.py"
    moved.write_text(
        "def retry_once(fn):\n"
        "    try:\n"
        "        return fn()\n"
        "    except TimeoutError:\n"
        "        return fn()\n"
    )
    move_sha = _commit(repo, "refactor: extract net helpers", "2023-09-09T10:00:00")

    return {"repo": str(repo), "path": "net.py", "origin_path": "util.py",
            "line": 5, "real_sha": real_sha, "noise_sha": move_sha}


def build_f5(dest: str) -> dict:
    """Revert then reintroduce: the strongest do-not-delete signal.

    Confirmed empirically: `git blame` on the target line only ever returns
    reintro_sha (the line's current content), never first_sha (the original
    introduction) -- that is simply how blame works, it reports the most
    recent commit that touched a line, not its full lineage. Recovering
    first_sha needs trace()'s pickaxe fallback: the needle
    "_poisoned" was added in first_sha, removed in revert_sha, and re-added
    in reintro_sha, so `git log -S _poisoned` surfaces all three. None of
    the three are noise (no vendor/generated/whitespace/merge signal, and
    files_changed is far below BREADTH_THRESHOLD so the keyword rules don't
    even apply), and revert/reapply subjects are deliberately outside
    noise.py's keyword regexes, so nothing here needs new tracer code:
    revert_chain's noise-independent collection and the existing pickaxe
    fallback (both already in trace()) are what make this pass.
    """
    repo = _init(dest, "f5")
    target = repo / "cache.py"
    target.write_text("def get(key):\n    return store[key]\n")
    _commit(repo, "feat: add cache get", "2021-01-01T10:00:00")

    target.write_text(
        "def get(key):\n"
        "    if key in _poisoned:\n"
        "        return None\n"
        "    return store[key]\n"
    )
    real_sha = _commit(repo, "fix: bypass poisoned cache keys (#310)",
                       "2021-05-05T10:00:00")

    target.write_text("def get(key):\n    return store[key]\n")
    revert_sha = _commit(repo, 'Revert "fix: bypass poisoned cache keys (#310)"',
                         "2021-05-20T10:00:00")

    target.write_text(
        "def get(key):\n"
        "    if key in _poisoned:\n"
        "        return None\n"
        "    return store[key]\n"
    )
    reintro_sha = _commit(repo, "fix: reapply poisoned key bypass (#318)",
                          "2021-06-02T10:00:00")

    return {"repo": str(repo), "path": "cache.py", "line": 3,
            "real_sha": reintro_sha, "first_sha": real_sha,
            "revert_sha": revert_sha, "reintro_sha": reintro_sha,
            "noise_sha": revert_sha}


def build_f6(dest: str) -> dict:
    """N6: a vendoring commit dumps hundreds of files.

    A vendor dump that is fully unrelated to the target file is not, on its
    own, a trap: verified empirically that with noise.py's N6 check disabled
    entirely, the vendor commit still never appears in introduction_candidates,
    because it never touches app.py, so blame/line-history (both path-scoped)
    never see it, and none of app.py's pickaxe needles happen to occur inside
    the vendored filler ("/* vendored */"). The assertion that the vendor
    commit is absent from candidates would then pass for a reason that has
    nothing to do with noise.py.

    To make this an actual trap, one vendored file coincidentally (in
    practice: deliberately) contains "load_config", one of the needles
    trace._needles draws from app.py's target line. That makes the vendor
    commit a genuine pickaxe hit for this trace (confirmed empirically via
    gitq.pickaxe), so it would enter introduction_candidates were it not for
    noise.py's structural N6 check (all changed paths under vendor/), which
    is the thing this fixture exists to prove exercises.
    """
    repo = _init(dest, "f6")
    target = repo / "app.py"
    target.write_text("def boot():\n    return load_config()\n")
    real_sha = _commit(repo, "feat: boot app", "2022-01-01T10:00:00")

    vendor = repo / "vendor" / "libx"
    vendor.mkdir(parents=True)
    for i in range(24):
        (vendor / "f{}.c".format(i)).write_text("/* vendored */\n")
    (vendor / "f24.c").write_text("/* load_config vendored stub */\n")
    vendor_sha = _commit(repo, "deps: vendor libx", "2022-02-01T10:00:00")

    return {"repo": str(repo), "path": "app.py", "line": 2,
            "real_sha": real_sha, "vendor_sha": vendor_sha,
            "noise_sha": vendor_sha}


def build_f7(dest: str) -> dict:
    """N9: merge commits clutter the first-parent line.

    A conflict-free merge (feature branch changes auth.py; main only adds an
    unrelated file) is not a trap: verified empirically, with noise.py's N9
    check disabled entirely, the merge commit still never appears in
    introduction_candidates, because a fast-forward-able merge never becomes
    a blame candidate (git blame resolves straight through to the branch
    commit that made the only real change) and it is never a pickaxe or
    line-history hit either (it does not touch the string being searched for,
    and -S/-L do not surface merges whose diff is empty against one parent).
    The "merge commit excluded" assertion would then pass whether or not
    noise.py's N9 rule exists.

    git blame is in fact quite good at seeing through merges: even when both
    branches touch the very same line and the merge requires a real conflict
    resolution, blame still attributes the result to whichever parent's
    commit its final byte-for-byte content matches, walking straight past the
    merge. It only attributes a line to the merge commit itself when the
    manual resolution produces content that does not match either parent
    verbatim, i.e. is a genuine synthesis of both sides. This fixture forces
    exactly that: main and the feature branch each add a different keyword
    argument to the same call, so merging conflicts, and the hand-resolved
    line combines both (retries=3 from the feature fix, source='main' from
    main) into text that existed nowhere before. Confirmed empirically that
    `git blame -w -C -C -C` on that combined line then attributes it to the
    merge commit itself (parents_count=2), which noise.py classifies N9
    unconditionally, so this fixture actually exercises the exclusion. The
    feature fix's own token ("retries") is unaffected by the merge (its
    occurrence count does not change across the merge), so pickaxe still
    finds the real fix commit directly through it.
    """
    repo = _init(dest, "f7")
    target = repo / "auth.py"
    target.write_text("def login(u):\n    return session(u)\n")
    _commit(repo, "feat: add login", "2022-03-01T10:00:00")

    _git(repo, "checkout", "-q", "-b", "feature")
    target.write_text("def login(u):\n    return session(u, retries=3)\n")
    real_sha = _commit(repo, "fix: retry session on transient auth failure (#512)",
                       "2022-03-05T10:00:00")

    _git(repo, "checkout", "-q", "main")
    target.write_text("def login(u):\n    return session(u, source='main')\n")
    _commit(repo, "chore: tag session source", "2022-03-04T10:00:00")

    # This merge conflicts by construction: main and feature each add a
    # different keyword argument to the same call since diverging. Let it
    # fail, then resolve by hand, combining both sides.
    env = dict(os.environ)
    env.update(ENV)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(
        ["git", "merge", "--no-ff", "-q", "-m", "Merge branch 'feature'", "feature"],
        cwd=repo, capture_output=True, text=True, env=env,
    )
    target.write_text("def login(u):\n    return session(u, retries=3, source='main')\n")
    merge_sha = _commit(repo, "Merge branch 'feature'", "2022-03-06T10:00:00")

    return {"repo": str(repo), "path": "auth.py", "line": 2,
            "real_sha": real_sha, "merge_sha": merge_sha,
            "noise_sha": merge_sha}


def build_f4(dest: str) -> dict:
    """N10: history was squashed, so intent lives only in the PR title."""
    repo = _init(dest, "f4")
    target = repo / "session.py"
    target.write_text("def touch(s):\n    s.seen_at = now()\n")
    _commit(repo, "feat: add session touch", "2022-06-01T10:00:00")

    target.write_text(
        "def touch(s):\n"
        "    if s.idle_seconds > 900:\n"
        "        s.rotate_token()\n"
        "    s.seen_at = now()\n"
    )
    for i in range(25):
        (repo / "unrelated_{}.py".format(i)).write_text("x = {}\n".format(i))
    squash_sha = _commit(
        repo, "Rotate token on idle sessions and reformat module (#2211)",
        "2022-07-01T10:00:00")

    return {"repo": str(repo), "path": "session.py", "line": 3,
            "real_sha": squash_sha, "pr_number": 2211, "noise_sha": squash_sha}


def build_two_renames(dest: str) -> dict:
    """A file renamed twice, each rename plain (no bundled unrelated edits),
    with a few unrelated edits at each path in between.

    Regression fixture for the field report behind the 0.2.1 release: a real
    trace was miscounted at 4 commits by `git log --oneline -- <path>` (no
    `--follow`), when the actual lineage was 21 commits once renames were
    followed, because that command only ever counts commits that touched the
    file's *current* path. This fixture reproduces the shape, not the exact
    counts: `git log --oneline -- <path>` (no `--follow`) counts only the
    commits made after the second rename, while `git log --oneline --follow
    -- <path>` (or `trace()`, which never relies on path-scoped counting to
    begin with) sees the full lineage back to the real introducing commit.

    Both renames are plain `git mv` with no other change bundled into the
    same commit, deliberately unlike F2's bundled rename: F2 exists to prove
    a *bundled* rename can defeat `git blame -w -C -C -C`'s own move
    detection; this fixture exists to prove the *no-follow commit count* is
    wrong regardless of whether blame itself is defeated. A plain rename
    lets blame follow it on its own (see F2's docstring), so `real_sha`
    reaches `introduction_candidates` here via blame, with nothing left for
    the pickaxe or line-history fallback to do; that is the point, not an
    oversight. If a future change to `gitq.blame_shas` ever weakens plain-
    rename tracking, `TestTwoRenames.test_finds_real_commit_despite_two_renames`
    below would catch it.
    """
    repo = _init(dest, "two_renames")
    target = repo / "payment.py"
    target.write_text("def charge(order):\n    return order.total\n")
    _commit(repo, "feat: add charge", "2020-01-05T10:00:00")

    target.write_text(
        "def charge(order):\n"
        "    if order.region == 'EU':\n"
        "        return order.total_with_vat\n"
        "    return order.total\n"
    )
    real_sha = _commit(repo, "feat: apply EU VAT (#901)", "2020-04-11T10:00:00")

    for i, date in enumerate([
        "2020-05-01T10:00:00", "2020-06-01T10:00:00", "2020-07-01T10:00:00",
    ]):
        target.write_text(target.read_text() + "# note {}\n".format(i))
        _commit(repo, "chore: tweak payment note {}".format(i), date)

    billing = repo / "billing_payment.py"
    _git(repo, "mv", "payment.py", "billing_payment.py")
    _commit(repo, "refactor: move payment into billing", "2021-01-01T10:00:00")

    for i, date in enumerate([
        "2021-02-01T10:00:00", "2021-03-01T10:00:00", "2021-04-01T10:00:00",
    ]):
        billing.write_text(billing.read_text() + "# billing note {}\n".format(i))
        _commit(repo, "chore: tweak billing note {}".format(i), date)

    core_dir = repo / "core"
    core_dir.mkdir()
    final = core_dir / "billing.py"
    _git(repo, "mv", "billing_payment.py", "core/billing.py")
    _commit(repo, "refactor: consolidate billing under core", "2022-01-01T10:00:00")

    for i, date in enumerate(["2022-02-01T10:00:00", "2022-03-01T10:00:00"]):
        final.write_text(final.read_text() + "# core note {}\n".format(i))
        _commit(repo, "chore: tweak core billing note {}".format(i), date)

    lines = final.read_text().splitlines()
    line = next(i for i, l in enumerate(lines, 1) if "total_with_vat" in l)

    return {
        "repo": str(repo),
        "path": "core/billing.py",
        "line": line,
        "real_sha": real_sha,
    }


def build_candidate_cap_probe(dest: str) -> dict:
    """A target line whose distinctive token also appears, one at a time,
    in three unrelated commits touching three unrelated files.

    Regression fixture for trace()'s total-candidate cap (max_candidates).
    The target file's own commit is found through blame (exempt from the
    cap); the three unrelated commits are only found through pickaxe, so
    they are exactly the kind of addition the cap is meant to bound. With
    a very small max_candidates, at least one of them must be dropped and
    reported, while the default max_candidates must keep all of them.
    """
    repo = _init(dest, "candidate_cap_probe")
    target = repo / "target.py"

    target.write_text('MAGIC = "zzz_needle_token"\n')
    _commit(repo, "feat: add magic", "2019-01-01T10:00:00")

    for i in range(1, 4):
        other = repo / "other{}.py".format(i)
        other.write_text('X = "zzz_needle_token"\n')
        _commit(repo, "feat: mention token in other{}".format(i),
                "2019-01-0{}T10:00:00".format(i + 1))

    return {
        "repo": str(repo),
        "path": "target.py",
        "line": 1,
    }


def build_deep_history(dest: str) -> dict:
    """A single file modified 113 times, with the real introducing commit
    buried early and its line touched again, trivially, by the last of 110
    filler commits, so a single `git blame` call names only that last
    trivial touch.

    Not F1 through F7 and not N-numbered: this fixture is not exercised by
    noise.py's classifier tests. It exists for tests/pressure scenarios
    that need genuinely deep history, where reading "everything" is a real
    cost, not the 3-commit F1 fixture where a full `git log -p` finishes
    in seconds and there is no actual temptation to stop early.

    Construction: the real fix (`real_sha`) adds a guard clause early
    (2018-01-15). 110 filler commits follow, one per day, each rewriting
    only a build-marker comment on line 1 of the file; the guard block
    itself (lines 2-5) is byte-identical across all 110, so blame would
    still correctly attribute the guard line to `real_sha` if nothing else
    ever touched it. The final commit (`noise_sha`, "chore: apply
    formatter") does touch the guard line itself, a single-quote-to-
    double-quote change, so it is what `git blame` reports for that line:
    a real signal for why the line exists is buried 111 commits back from
    the tip, cheap to find with `git log -S` but expensive to find by
    reading the full `git log -p` top to bottom, which is exactly the
    temptation this fixture is meant to create under time pressure.

    Dates are fixed absolute values, not relative to "now", for the same
    determinism reason as every other fixture in this module.

    The base commit's comment ("SecurityError policy... arrives later")
    is deliberate, not filler: it plants the same rare identifier the
    guard clause later raises (`SecurityError`) in an older, unrelated
    commit, so this fixture still demonstrates trace.py's
    position-vs-meaning trap (an older, non-introducing commit sharing a
    pickaxe needle with the target line, see
    test_render_m1_m2.py::OlderTokenCollisionCase) under trace.py's
    ranked, capped needle selection. Before that ranking existed, a plain
    English word shared between this commit and the target line
    (`token`) was enough to cause the same collision; ranking now
    deprioritizes exactly that kind of common word in favor of
    distinctive identifiers, so demonstrating the same trap honestly
    needs a distinctive identifier here instead.
    """
    repo = _init(dest, "deep_history")
    target = repo / "session_guard.py"

    target.write_text(
        "def authorize(token):\n"
        "    # SecurityError policy: reject replayed tokens, arrives later\n"
        "    return token.user\n"
    )
    _commit(repo, "feat: add authorize", "2018-01-01T10:00:00")

    target.write_text(
        "def authorize(token):\n"
        "    if token.is_replayed():\n"
        "        raise SecurityError('replayed token rejected')\n"
        "    return token.user\n"
    )
    real_sha = _commit(
        repo, "fix: reject replayed session tokens after logout (#5521)",
        "2018-01-15T10:00:00")

    filler_start = datetime(2018, 1, 16, 10, 0, 0)
    for i in range(110):
        date = (filler_start + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S")
        target.write_text(
            "# build {}\n".format(i)
            + "def authorize(token):\n"
            "    if token.is_replayed():\n"
            "        raise SecurityError('replayed token rejected')\n"
            "    return token.user\n"
        )
        _commit(repo, "chore: bump build marker {}".format(i), date)

    final_date = (filler_start + timedelta(days=110)).strftime("%Y-%m-%dT%H:%M:%S")
    target.write_text(
        "# build 110\n"
        "def authorize(token):\n"
        "    if token.is_replayed():\n"
        '        raise SecurityError("replayed token rejected")\n'
        "    return token.user\n"
    )
    noise_sha = _commit(repo, "chore: apply formatter", final_date)

    return {
        "repo": str(repo),
        "path": "session_guard.py",
        "line": 4,
        "real_sha": real_sha,
        "noise_sha": noise_sha,
        "total_commits": 113,
    }


def build_needle_junk_probe(dest: str) -> dict:
    """A target line combining one rare, genuinely distinctive identifier
    with one common, equally identifier-shaped token that nonetheless
    appears across many other files in the current tree.

    Regression fixture for trace.py's needle rarity check
    (`gitq.grep_match_file_count`, used by `_select_needles`). Before that
    check existed, needle ranking looked at shape alone (length, presence
    of `_`/`.`), and `configuration_value_holder` (26 characters,
    underscored) out-ranks `checksum_retry_guard` (20 characters,
    underscored) by that measure alone despite being the worse needle:
    it is deliberately planted, one file at a time, across 20 unrelated
    commits that never touch `target.py`, so a repo-wide pickaxe search
    on it alone floods introduction_candidates with all 20. The rarity
    check is what tells them apart: at HEAD, `configuration_value_holder`
    appears in 21 files (target.py plus the 20 planted ones), comfortably
    over trace.py's common-token threshold, while `checksum_retry_guard`
    appears only in target.py.
    """
    repo = _init(dest, "needle_junk_probe")
    target = repo / "target.py"
    target.write_text("VALUE = 1\n")
    _commit(repo, "feat: add target", "2019-01-01T10:00:00")

    target.write_text(
        "VALUE = 1\n"
        "result = checksum_retry_guard(configuration_value_holder)\n"
    )
    real_sha = _commit(
        repo, "fix: guard against retried checksum mismatches (#88)",
        "2019-02-01T10:00:00")

    junk_shas = []
    for i in range(20):
        other = repo / "other{}.py".format(i)
        other.write_text("configuration_value_holder = {}\n".format(i))
        sha = _commit(repo, "chore: add config holder {}".format(i),
                      "2019-03-{:02d}T10:00:00".format(i + 1))
        junk_shas.append(sha)

    return {
        "repo": str(repo),
        "path": "target.py",
        "line": 2,
        "real_sha": real_sha,
        "junk_shas": junk_shas,
        "common_token": "configuration_value_holder",
        "rare_token": "checksum_retry_guard",
    }


def build_activity_probe(dest: str) -> dict:
    """A single-line file touched by two authors across a known split of
    old and recent commits, for testing trace.py's activity computation
    (last touch, commits in the last year, main authors) against ground
    truth rather than against "however many commits happen to exist".

    Dates are relative to "now" (`_days_ago`), deliberately unlike every
    other fixture in this module: the fact under test, "commits in the
    last year", is itself relative to "now", so a fixed historical date
    would drift out of (or never enter) the window depending on when the
    test happens to run.

    Five commits: two by Alice more than a year old (outside the
    `--since "1 year ago"` window trace.py uses), two by Bob within the
    window, and a fifth by Alice, also within the window, that is the
    file's most recent touch. Since the file is a single line, every
    commit touches the target line directly, so "last touched (target
    lines)" and "last touched (file)" agree here; that distinction is
    exercised separately (see the line-history-unavailable case in
    test_trace_report_additions.py). Expected facts:
      - commits_last_year: 3 (Bob's two, plus Alice's most recent)
      - top_authors by total history: Alice 3, Bob 2
      - last_touch: Alice's most recent commit
    """
    repo = _init(dest, "activity_probe")
    target = repo / "svc.py"

    def _commit_as(message, days_ago, name, email):
        env = dict(os.environ)
        env.update(ENV)
        env["GIT_AUTHOR_NAME"] = name
        env["GIT_AUTHOR_EMAIL"] = email
        env["GIT_COMMITTER_NAME"] = name
        env["GIT_COMMITTER_EMAIL"] = email
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        date = _days_ago(days_ago)
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
        subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True,
                        capture_output=True, text=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, env=env,
                        check=True, capture_output=True, text=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, env=env,
                               capture_output=True, text=True, check=True).stdout.strip()

    target.write_text("VALUE = 0\n")
    _commit_as("feat: add value", 800, "Alice", "alice@example.com")

    target.write_text("VALUE = 1\n")
    _commit_as("chore: alice tweak", 750, "Alice", "alice@example.com")

    target.write_text("VALUE = 2\n")
    _commit_as("chore: bob tweak one", 300, "Bob", "bob@example.com")

    target.write_text("VALUE = 3\n")
    _commit_as("chore: bob tweak two", 200, "Bob", "bob@example.com")

    target.write_text("VALUE = 4\n")
    last_sha = _commit_as("chore: alice most recent tweak", 10, "Alice", "alice@example.com")

    return {
        "repo": str(repo),
        "path": "svc.py",
        "line": 1,
        "last_sha": last_sha,
        "commits_last_year": 3,
        "top_author": "Alice",
        "top_author_count": 3,
        "second_author": "Bob",
        "second_author_count": 2,
    }


def build_no_needle_target(dest: str) -> dict:
    """A target line with no pickaxe-needle-shaped tokens at all (a bare
    numeric literal, so `trace._WORD` finds nothing on it), for testing
    that the reproduction-commands section omits the pickaxe search
    entirely when `_select_needles` legitimately selects none, rather
    than fabricating one (see render.py's `_repro_html`).
    """
    repo = _init(dest, "no_needle_target")
    target = repo / "const.py"
    target.write_text("def get():\n    42\n")
    real_sha = _commit(repo, "feat: add magic constant", "2020-01-01T10:00:00")
    return {"repo": str(repo), "path": "const.py", "line": 2, "real_sha": real_sha}


def build_binary_target(dest: str) -> dict:
    """A target path whose content at HEAD is binary, for testing that
    trace.py's snippet computation (`_compute_snippet`) degrades to
    `{"available": False, "reason": "binary"}` instead of crashing or
    handing render.py bytes it cannot safely treat as text.
    """
    repo = _init(dest, "binary_target")
    target = repo / "blob.bin"
    target.write_bytes(b"\x00\x01\x02binary\xff\xfe\xfd")
    sha = _commit(repo, "feat: add binary blob", "2021-01-01T10:00:00")
    return {"repo": str(repo), "path": "blob.bin", "line": 1, "sha": sha}


def build_undecodable_no_nul_target(dest: str) -> dict:
    """A target path whose content at HEAD fails to decode as UTF-8 but
    contains no NUL byte at all, for testing that trace.py's snippet
    computation reaches its `"binary"` reason through the decode-failure
    path specifically, not only through the NUL-byte check that runs
    first (see `build_binary_target`, whose content trips the NUL check
    before decoding is ever attempted). `0xff` is not a valid UTF-8
    leading byte anywhere, and the content below has none of the NUL
    bytes `build_binary_target`'s does.
    """
    repo = _init(dest, "undecodable_no_nul_target")
    target = repo / "blob_no_nul.bin"
    target.write_bytes(b"abc\xffdef\n")
    sha = _commit(repo, "feat: add undecodable blob", "2021-01-01T10:00:00")
    return {"repo": str(repo), "path": "blob_no_nul.bin", "line": 1, "sha": sha}


def build_line_break_divergence(dest: str, *, name: str = "line_break_divergence",
                                 divergent: bytes = b"") -> dict:
    """A file with `divergent` bytes spliced between two short lines near
    the top, and a target several lines further down -- for testing
    trace.py's snippet reader against the real git-read path (not just
    the pure `_has_splitlines_divergence` predicate in isolation), for
    each of the nine characters that make `str.splitlines()` disagree
    with the plain "\\n" split `patch.py` and `git apply` use, plus the
    negative controls that must NOT be flagged.

    `divergent=b""` (the default) is the plain-LF negative control: no
    divergent bytes at all, still an ordinary multi-line file. Passing
    `b"\\r\\n"` is the CRLF negative control: a real line ending, not a
    lone divergent character, so a Windows-authored file must not be
    refused either. Passing any single one of trace.py's
    `_SPLITLINES_ONLY_BREAKS` characters, or a lone `b"\\r"`, is the
    positive case: since the divergence sits near the top and the target
    sits near the bottom, this always exercises the "before the target"
    position, the one that actually shifts every recorded line number
    downstream of it.

    The target line number is computed from `divergent`'s own byte
    content rather than assumed, since `divergent` can itself contain a
    "\\n" (as `b"\\r\\n"` does), changing how many git-counted lines the
    prefix chunk becomes.
    """
    repo = _init(dest, name)
    target = repo / "m.py"
    prefix = b"a = 1" + divergent + b"b = 2\n"
    filler = b"".join("v{:02d} = {}\n".format(i, i).encode() for i in range(3, 9))
    content = prefix + filler + b"TARGET = 42\n"
    target.write_bytes(content)
    sha = _commit(repo, "feat: add stuff", "2021-01-01T10:00:00")
    lines = content.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    target_line = len(lines)  # "TARGET = 42" is always the last real line
    return {"repo": str(repo), "path": "m.py", "line": target_line, "sha": sha}


def build_korean_paths(dest: str) -> dict:
    """Korean commit messages and a Korean target filename, co-changed with
    a Korean-named test file under an ASCII `tests/` directory.

    Regression fixture for the `core.quotepath` bug: with git's default
    `core.quotepath=true`, `git show --name-only` prints non-ASCII paths
    octal-escaped and wrapped in double quotes (e.g.
    `"\\352\\262\\260\\354\\240\\234\\353\\252\\250\\353\\223\\210.py"`
    instead of "결제모듈.py"). That breaks three things at once: the
    target file's own path never string-equals its escaped form, so
    self-exclusion (trace.py's `p != path` check) fails and the target
    shows up in its own co-changed list; the leading quote character
    corrupts `posixpath.split`, so `noise.is_test_path` can no longer
    recognize the (perfectly ordinary, ASCII) `tests/` directory segment
    once the rest of the path is non-ASCII; and render.py would show the
    raw escaped garbage to the user. This fixture reproduces all three in
    one commit so the fix (`-c core.quotepath=off` on the git call that
    lists changed paths) can be pinned with a single trace.
    """
    repo = _init(dest, "korean")
    target = repo / "결제모듈.py"
    target.write_text("def charge(order):\n    return order.total\n")
    test_dir = repo / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    # Deliberately no English "test"/"spec" filename marker: recognition
    # here must come from the ASCII `tests/` directory segment alone, not
    # from a filename suffix, so the fixture actually exercises the
    # directory-segment path in `noise.is_test_path` rather than
    # accidentally passing for an unrelated reason.
    test_file = test_dir / "결제_확인.py"
    test_file.write_text("def check_charge():\n    pass\n")
    real_sha = _commit(repo, "핫픽스: 중복 결제 방지 (#521)",
                       "2022-05-01T09:00:00")

    return {
        "repo": str(repo),
        "path": "결제모듈.py",
        "line": 1,
        "real_sha": real_sha,
        "test_path": "tests/결제_확인.py",
    }


def build_body_message(dest: str, *, body: str = None,
                       name: str = "body_message") -> dict:
    """A commit whose subject says almost nothing and whose body says why.

    The common real shape, and the reason `trace.py` carries `body` for
    every candidate: `fix: guard charge` tells an agent nothing it can
    grade, while the body names the incident. Used by
    tests/test_candidate_body.py, including with an oversized `body` to
    pin the truncation disclosure.
    """
    if body is None:
        body = ("Customers were charged twice when the webhook was delivered "
                "more than once. Adding an early return on an already "
                "processed order.\n\nRefs #4127")
    repo = _init(dest, name)
    target = repo / "payment.py"

    target.write_text("def charge(order):\n    order.mark_processed()\n")
    _commit(repo, "feat: add charge", "2019-01-05T10:00:00")

    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return {'status': 'duplicate'}\n"
        "    order.mark_processed()\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix: guard charge", "-m", body,
         date="2019-11-08T02:14:00")
    real_sha = _git(repo, "rev-parse", "HEAD")

    return {"repo": str(repo), "path": "payment.py", "line": 3,
            "real_sha": real_sha, "body": body}


def build_commented_out(dest: str, *, name: str = "commented_out") -> dict:
    """Six shapes of comment block in one repository, of which exactly two
    are commented-out code.

    1. `outage_sha` comments out five lines during an incident and says why
       in the commit body. A candidate, and `look_first`.
    2. `refactor_sha` comments out four lines with no body. A candidate,
       not `look_first`.
    3. A TODO run of four lines. Not a candidate.
    4. A license header. Not a candidate.
    5. A commented-out block under `vendor/`. Skipped as vendored.
    6. A commented-out block in `README.rst`. Skipped as an unsupported
       extension, and counted as one.

    Dates are fixed, and `scan()` takes an injectable `now`, so the
    age ordering these fixtures exercise is deterministic.
    """
    repo = _init(dest, name)
    (repo / "vendor").mkdir()

    live = repo / "billing.py"
    other = repo / "notes.py"
    licensed = repo / "licensed.py"
    vendored = repo / "vendor" / "thirdparty.py"
    # A tracked file whose extension is not in COMMENT_MARKERS, so the
    # unsupported-extension count has something real to count. An
    # untracked file would not do: `ls-files` never lists it, so the count
    # would be zero either way and the test would pass without testing.
    unsupported = repo / "README.rst"

    live.write_text(
        "def charge(order):\n"
        "    return gateway.charge(order)\n"
    )
    other.write_text(
        "# TODO: split this module once the migration lands\n"
        "# TODO: and drop the compatibility shim below\n"
        "# TODO: see the platform channel for context\n"
        "# TODO: owner is the billing team\n"
        "def helper():\n"
        "    return 1\n"
    )
    licensed.write_text(
        "# Copyright 2020 Example Inc.\n"
        "# SPDX-License-Identifier: MIT\n"
        "# Licensed under the terms above.\n"
        "def ok():\n"
        "    return True\n"
    )
    unsupported.write_text("Docs\n====\n\n# def looks_like_code(x):\n#     return x\n#     pass\n")
    vendored.write_text(
        "# def vendored_dead(x):\n"
        "#     return x.compute()\n"
        "#     raise NotImplementedError()\n"
        "def vendored_live():\n"
        "    return 0\n"
    )
    _commit(repo, "feat: 결제 기반 추가", "2019-01-05T10:00:00")

    # 1. The incident: retry logic commented out, reason in the body.
    live.write_text(
        "def charge(order):\n"
        "    # if order.retryable:\n"
        "    #     for attempt in range(3):\n"
        "    #         gateway.charge(order)\n"
        "    #     return None\n"
        "    # end retry\n"
        "    return gateway.charge(order)\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "hotfix: 게이트웨이 장애로 재시도 비활성화",
         "-m", "게이트웨이가 502를 계속 반환해서 재시도를 임시로 끕니다. #3391 해결 후 되살릴 것.",
         date="2021-06-14T09:12:00")
    outage_sha = _git(repo, "rev-parse", "HEAD")

    # 2. The refactoring leftover: no body, later date.
    other.write_text(
        "# TODO: split this module once the migration lands\n"
        "# TODO: and drop the compatibility shim below\n"
        "# TODO: see the platform channel for context\n"
        "# TODO: owner is the billing team\n"
        "# def old_fee(amount):\n"
        "#     rate = lookup(amount)\n"
        "#     return amount * rate\n"
        "# end old_fee\n"
        "def helper():\n"
        "    return 1\n"
    )
    refactor_sha = _commit(repo, "refactor: 수수료 계산 헬퍼 정리",
                            "2023-11-02T10:00:00")

    return {
        "repo": str(repo),
        "outage_sha": outage_sha,
        "refactor_sha": refactor_sha,
        "outage_path": "billing.py",
        "refactor_path": "notes.py",
    }


def build_ordering_probe(dest: str, *, name: str = "ordering_probe") -> dict:
    """Two commented-out blocks whose alphabetical and chronological order
    disagree, so that `scan()`'s oldest-first sort is exercised for real.

    `aaa_recent.py` sorts first alphabetically (and `ls-files` lists it
    first) but its block was commented out in 2024. `zzz_old.py` sorts
    last but its block was commented out in 2019. A `scan()` that dropped
    its sort key and simply returned candidates in `ls-files`/discovery
    order would put `aaa_recent.py` first; only a real oldest-first sort
    puts `zzz_old.py` first.
    """
    repo = _init(dest, name)
    recent = repo / "aaa_recent.py"
    old = repo / "zzz_old.py"

    recent.write_text(
        "def charge(order):\n"
        "    return gateway.charge(order)\n"
    )
    old.write_text(
        "def refund(order):\n"
        "    return gateway.refund(order)\n"
    )
    _commit(repo, "feat: 초기 결제/환불 모듈 추가", "2018-01-01T10:00:00")

    old.write_text(
        "def refund(order):\n"
        "    # if order.disputed:\n"
        "    #     for step in range(3):\n"
        "    #         gateway.refund(order)\n"
        "    #     return None\n"
        "    return gateway.refund(order)\n"
    )
    old_sha = _commit(repo, "refactor: 환불 재시도 경로 정리", "2019-03-01T10:00:00")

    recent.write_text(
        "def charge(order):\n"
        "    # if order.retryable:\n"
        "    #     for attempt in range(3):\n"
        "    #         gateway.charge(order)\n"
        "    #     return None\n"
        "    return gateway.charge(order)\n"
    )
    recent_sha = _commit(repo, "refactor: 결제 재시도 경로 정리", "2024-03-01T10:00:00")

    return {
        "repo": str(repo),
        "old_path": "zzz_old.py",
        "recent_path": "aaa_recent.py",
        "old_sha": old_sha,
        "recent_sha": recent_sha,
    }


def build_touched_twice(dest: str, *, name: str = "touched_twice") -> dict:
    """One commented-out block whose blame range carries two shas: an older
    commit comments the block out, then a later commit edits one line
    inside that same commented block (a comment typo fix, a rephrase of
    the intent note, anything that rewrites content rather than deleting
    or adding a line).

    This is the fixture `test_oldest_of_several_blame_shas` needs: every
    block in `build_commented_out` above carries exactly one blame sha,
    so `_oldest`'s "pick the oldest of several, report how many" behavior
    has nothing to exercise without this one.
    """
    repo = _init(dest, name)
    target = repo / "billing_retry.py"

    target.write_text(
        "def charge(order):\n"
        "    return gateway.charge(order)\n"
    )
    _commit(repo, "feat: 결제 모듈 추가", "2019-01-01T10:00:00")

    target.write_text(
        "def charge(order):\n"
        "    # if order.retryable:\n"
        "    #     for attempt in range(3):\n"
        "    #         gateway.charge(order)\n"
        "    #     return None\n"
        "    return gateway.charge(order)\n"
    )
    older_sha = _commit(repo, "hotfix: 재시도 로직 임시 비활성화", "2020-01-01T10:00:00")

    target.write_text(
        "def charge(order):\n"
        "    # if order.retryable:\n"
        "    #     for attempt in range(5):\n"
        "    #         gateway.charge(order)\n"
        "    #     return None\n"
        "    return gateway.charge(order)\n"
    )
    later_sha = _commit(repo, "chore: 주석 속 재시도 횟수 표기 수정", "2022-01-01T10:00:00")

    return {
        "repo": str(repo),
        "path": "billing_retry.py",
        "older_sha": older_sha,
        "later_sha": later_sha,
        "start": 2,
        "end": 5,
    }


def build_timezone_skew(dest: str, *, name: str = "timezone_skew") -> dict:
    """Commit dates whose text order and instant order disagree, because
    the commits were authored in different timezones.

    Every other fixture in this module passes offset-free dates, so
    lexicographic order over `%aI` accidentally equalled chronological
    order and a string sort passed for the wrong reason. Here it cannot:

    - `alpha.py`: `outage_sha` comments five lines out at
      2020-03-02T02:00:00+09:00, which is 2020-03-01T17:00Z, and says why
      in an incident subject. `chore_sha` rewrites one line inside that
      same commented block eight hours later at 2020-03-01T20:00:00-05:00,
      which is 2020-03-02T01:00Z. `chore_sha`'s date string sorts first
      and its instant is later, so a text sort reports the chore as the
      commenting commit, drops the incident commit entirely, and turns
      `look_first` off.
    - `beta.py`: commented out at 2020-03-01T19:00:00-11:00, which is
      2020-03-02T06:00Z, the newest instant of the three, while its date
      string sorts before both of `alpha.py`'s. A text sort therefore
      lists `beta.py` first; only a sort by instant puts `alpha.py`, the
      genuinely older block, at the top.
    """
    repo = _init(dest, name)
    alpha = repo / "alpha.py"
    beta = repo / "beta.py"

    alpha.write_text(
        "def charge(order):\n"
        "    return gateway.charge(order)\n"
    )
    beta.write_text(
        "def refund(order):\n"
        "    return gateway.refund(order)\n"
    )
    _commit(repo, "feat: 결제/환불 모듈 추가", "2019-01-01T10:00:00+00:00")

    alpha.write_text(
        "def charge(order):\n"
        "    # if order.retryable:\n"
        "    #     for attempt in range(3):\n"
        "    #         gateway.charge(order)\n"
        "    #     return None\n"
        "    return gateway.charge(order)\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "hotfix: 게이트웨이 장애로 재시도 비활성화",
         "-m", "게이트웨이가 502를 계속 반환해서 재시도를 임시로 끕니다.",
         date="2020-03-02T02:00:00+09:00")
    outage_sha = _git(repo, "rev-parse", "HEAD")

    alpha.write_text(
        "def charge(order):\n"
        "    # if order.retryable:\n"
        "    #     for attempt in range(5):\n"
        "    #         gateway.charge(order)\n"
        "    #     return None\n"
        "    return gateway.charge(order)\n"
    )
    chore_sha = _commit(repo, "chore: 주석 속 재시도 횟수 표기 수정",
                         "2020-03-01T20:00:00-05:00")

    beta.write_text(
        "def refund(order):\n"
        "    # if order.disputed:\n"
        "    #     for step in range(3):\n"
        "    #         gateway.refund(order)\n"
        "    #     return None\n"
        "    return gateway.refund(order)\n"
    )
    beta_sha = _commit(repo, "refactor: 환불 재시도 경로 정리",
                        "2020-03-01T19:00:00-11:00")

    return {
        "repo": str(repo),
        "alpha_path": "alpha.py",
        "beta_path": "beta.py",
        "outage_sha": outage_sha,
        "chore_sha": chore_sha,
        "beta_sha": beta_sha,
        "start": 2,
        "end": 5,
    }


def build_block_comment(dest: str, *, name: str = "block_comment") -> dict:
    """A single Kotlin file with one `/* ... */` block of dead code and one
    `/** ... */` KDoc block right after it, for testing that block-comment
    detection (`scanner.find_blocks(..., block=...)`) finds exactly the
    dead code and discards the doc comment whole, per scanner.py's module
    docstring on why a `/**`-opened region is never split into candidates.

    The dead block (`oldCharge`) is four non-blank lines, each code-shaped
    (`fun`, `val`, `return`, and the bare `}` all match `_CODE_SHAPE`), so
    it clears both `MIN_BLOCK_LINES` and `CODE_SHAPE_RATIO`.

    The KDoc block (`legacyDiscount`) is deliberately also four code-shaped
    lines with no `@param`, no TODO, no license header and no blank-line
    dilution -- nothing `_NOT_CODE` would catch. Written this way on
    purpose: if it read as prose, or if any line inside it tripped
    `_NOT_CODE` and split the region below `MIN_BLOCK_LINES`, the doc
    comment would fail to become a candidate for a reason that has nothing
    to do with the `/**` exclusion, and the three tests below it would
    pass whether or not that exclusion exists. Confirmed empirically (see
    the fix report in .superpowers/sdd/2026-08-18-excerpt-and-block-comments/
    task-2-report.md): with the exclusion temporarily disabled, this exact
    body clears `MIN_BLOCK_LINES` and `CODE_SHAPE_RATIO` on its own and
    becomes a second candidate, so the exclusion is the only thing standing
    between this fixture and two candidates.
    """
    repo = _init(dest, name)
    target = repo / "Billing.kt"
    target.write_text(
        "class Billing {\n"
        "    /*\n"
        "    fun oldCharge(order: Order): Double {\n"
        "        val fee = 1.0\n"
        "        return order.total + fee\n"
        "    }\n"
        "    */\n"
        "\n"
        "    /**\n"
        "     * fun legacyDiscount(order: Order): Double {\n"
        "     *     val rate = 0.1\n"
        "     *     return order.total * rate\n"
        "     * }\n"
        "     */\n"
        "    fun applyDiscount(order: Order): Double {\n"
        "        return order.total\n"
        "    }\n"
        "}\n"
    )
    sha = _commit(repo, "refactor: 수수료 계산 로직 정리", "2022-04-01T10:00:00")

    return {
        "repo": str(repo),
        "path": "Billing.kt",
        "sha": sha,
    }


def build_patch_targets(dest: str, *, name: str = "patch_targets") -> dict:
    """Targets for `patch.py`, one per comment marker, in a working tree
    that matches HEAD.

    `git apply` patches the working tree, so what this fixture is really
    for is the file on disk; HEAD matters only because a trace reads its
    snippet from there, and a test that wants the "the file moved on since
    the investigation" refusal makes the two disagree by editing the file
    after the trace, not before.

    Each target line is indented, because the KEEP comment has to line up
    with it, and each has at least three lines above and below it so a
    three-line context hunk is a full one rather than a clamped edge case.
    `tail.py`'s target is the last line of a file with no trailing
    newline, which is the one shape a unified diff has to say something
    extra about (`\\ No newline at end of file`). `block.py`'s target
    spans four lines, so a comparison that only checked the first line of
    a target would be caught. `crlf.py` is the same Python target with
    CRLF endings. `blob.py` (undecodable bytes), `nul.py` (valid UTF-8
    holding a NUL byte) and `docs/fee.rst` (an extension no marker is
    known for) exist to be refused.

    `form_feed.py` holds a form feed character seventeen lines past its
    target, well outside the snippet's own recorded window, to reproduce
    I2's finding: the refusal must not depend on where in the file the
    divergent character happens to sit. `vtab.py` is the identical shape
    with a vertical tab instead, for N2's finding that the fix must not
    depend on which of the nine splitlines-only-break characters it is.

    `Ledger.kt` holds two methods of identical shape whose guard line is
    the bare `return` this project's Kotlin target already is, so a test
    can swap them (an ordinary refactor) and leave a line that matches the
    recorded target sitting at the recorded line number with somebody
    else's code around it. `edge.py`'s target is close enough to the end of
    the file that the patch's three lines of trailing context reach past
    it, which is how a test can put an uncommitted line inside the context
    of a patch and see whether the context was read from the working tree
    at all.

    Every returned line number is 1-based and points at the first line of
    the target, the line the comment goes directly above.
    """
    repo = _init(dest, name)

    python = repo / "billing" / "fee.py"
    python.parent.mkdir(parents=True)
    python.write_text(
        "import math\n"                                  # 1
        "\n"                                             # 2
        "\n"                                             # 3
        "def charge(order):\n"                           # 4
        "    if order.already_charged:\n"                # 5
        "        return {'status': 'duplicate'}\n"       # 6  <- target
        "    order.mark_processed()\n"                   # 7
        "    return order.total\n"                       # 8
        "\n"                                             # 9
        "\n"                                             # 10
        "def refund(order):\n"                           # 11
        "    return -order.total\n"                      # 12
    )

    kotlin = repo / "Fee.kt"
    kotlin.write_text(
        "package billing\n"                              # 1
        "\n"                                             # 2
        "class Fee {\n"                                  # 3
        "    fun charge(order: Order) {\n"               # 4
        "        if (order.alreadyCharged) {\n"          # 5
        "            return\n"                           # 6  <- target
        "        }\n"                                    # 7
        "        order.markProcessed()\n"                # 8
        "    }\n"                                        # 9
        "}\n"                                            # 10
    )

    # Two methods with the same shape, so swapping them is a refactor a
    # reviewer would wave through, and the guard line of each is the same
    # bare `return`. After the swap, line 6 is still `            return`
    # and belongs to the other method entirely.
    reorder = repo / "Ledger.kt"
    reorder.write_text(
        "package billing\n"                              # 1
        "\n"                                             # 2
        "class Ledger {\n"                               # 3
        "    fun charge(order: Order) {\n"               # 4
        "        if (order.alreadyCharged) {\n"          # 5
        "            return\n"                           # 6  <- target
        "        }\n"                                    # 7
        "        order.markProcessed()\n"                # 8
        "    }\n"                                        # 9
        "\n"                                             # 10
        "    fun refund(order: Order) {\n"               # 11
        "        if (order.refunded) {\n"                # 12
        "            return\n"                           # 13
        "        }\n"                                    # 14
        "        order.markRefunded()\n"                 # 15
        "    }\n"                                        # 16
        "}\n"                                            # 17
    )

    # The target sits two lines from the end, so the patch's three lines of
    # trailing context run one line past the end of the file as HEAD has
    # it. An uncommitted line appended on disk therefore lands inside the
    # hunk's context, where a patch built from the trace's snippet instead
    # of from the working tree cannot put it.
    edge = repo / "edge.py"
    edge.write_text(
        "def boot():\n"                                  # 1
        "    configure()\n"                              # 2
        "    if legacy_mode:\n"                          # 3
        "        return legacy_boot()\n"                 # 4  <- target
        "    return boot_v2()\n"                         # 5
    )

    sql = repo / "migrations" / "0001_fee.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text(
        "create table fee (\n"                           # 1
        "    id bigint primary key,\n"                   # 2
        "    order_id bigint not null,\n"                # 3
        "    amount numeric(12, 2) not null,\n"          # 4  <- target
        "    created_at timestamptz not null\n"          # 5
        ");\n"                                           # 6
        "\n"                                             # 7
        "create index fee_order_id on fee (order_id);\n" # 8
    )

    # A target spanning several lines, so the recorded-versus-disk
    # comparison has more than one line to compare. Every other target
    # here is a single line, which is exactly how a first-line-only
    # comparison could pass a whole test suite: an edit to line 6 or 8 of
    # this span has to be caught even though line 5 is untouched.
    block = repo / "block.py"
    block.write_text(
        "import math\n"                                  # 1
        "\n"                                             # 2
        "\n"                                             # 3
        "def charge(order):\n"                           # 4
        "    if order.already_charged:\n"                # 5  <- target start
        "        log.info('duplicate charge blocked')\n" # 6
        "        metrics.count('charge.duplicate')\n"    # 7
        "        return {'status': 'duplicate'}\n"       # 8  <- target end
        "    order.mark_processed()\n"                   # 9
        "    return order.total\n"                       # 10
    )

    # The target is the first line of the file, so the hunk has no context
    # above it at all and starts at line 1.
    head = repo / "head.py"
    head.write_text(
        "import legacy_shim\n"                           # 1  <- target
        "import math\n"                                  # 2
        "\n"                                             # 3
        "\n"                                             # 4
        "def boot():\n"                                  # 5
        "    return legacy_shim.boot()\n"                # 6
    )

    # No trailing newline: the target is the last line of the file.
    tail = repo / "tail.py"
    tail.write_text(
        "def boot():\n"                                  # 1
        "    configure()\n"                              # 2
        "    return run(retries=3)"                      # 3  <- target
    )

    # An extension absent from scanner.COMMENT_MARKERS, so there is a real
    # target for the "no marker is known" refusal to refuse.
    docs = repo / "docs" / "fee.rst"
    docs.parent.mkdir(parents=True)
    docs.write_text(
        "Fees\n"                                         # 1
        "====\n"                                         # 2
        "\n"                                             # 3
        "The duplicate guard is load bearing.\n"         # 4  <- target
        "\n"                                             # 5
        "See the billing runbook.\n"                     # 6
    )

    # Two ways for a file behind a known comment marker to fail to be
    # text, because they are two different code paths and one shadows the
    # other. `blob.py` does not decode as UTF-8 at all. `nul.py` decodes
    # perfectly well (a NUL byte is valid UTF-8) and is binary only by
    # git's own convention that a NUL byte makes it so, which is the case
    # the NUL check uniquely exists for.
    binary = repo / "blob.py"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00")

    nul = repo / "nul.py"
    nul.write_bytes(
        b"def charge(order):\n"
        b"    return order.total\x00\n"
        b"    # unreachable\n"
    )

    # CRLF, so the trace's snippet (read through `str.splitlines`, which
    # drops the "\r") and the working tree line (which keeps it) disagree
    # on bytes while naming the same line.
    crlf = repo / "crlf.py"
    crlf.write_bytes(
        b"import math\r\n"                                # 1
        b"\r\n"                                           # 2
        b"\r\n"                                           # 3
        b"def charge(order):\r\n"                         # 4
        b"    if order.already_charged:\r\n"              # 5
        b"        return {'status': 'duplicate'}\r\n"     # 6  <- target
        b"    order.mark_processed()\r\n"                 # 7
        b"    return order.total\r\n"                     # 8
    )

    # A form feed sitting well past the snippet's own recorded window
    # (target at line 3, `_SNIPPET_CONTEXT` reaches to line 7, form feed
    # at line 20 of 22): I2's exact far-divergence reproduction. Before
    # trace.py detected the form feed itself, `str.splitlines()`'s
    # line-break-on-form-feed only mis-numbered lines from 20 onward, so
    # the recorded window (lines 1-7) matched the working tree by
    # coincidence and a patch was built anyway.
    form_feed = repo / "form_feed.py"
    form_feed.write_text(
        "def charge(order):\n"                           # 1
        "    if order.already_charged:\n"                # 2
        "        return {'status': 'duplicate'}\n"       # 3  <- target
        "    order.mark_processed()\n"                   # 4
        "    return order.total\n"                       # 5
        "\n"                                             # 6
        "\n"                                             # 7
        "def refund(order):\n"                           # 8
        "    return -order.total\n"                       # 9
        "\n"                                             # 10
        "\n"                                             # 11
        "def audit_note():\n"                            # 12
        "    pass\n"                                      # 13
        "\n"                                             # 14
        "\n"                                             # 15
        "def another_helper():\n"                        # 16
        "    pass\n"                                      # 17
        "\n"                                             # 18
        "\n"                                             # 19
        "def report():\x0c\n"                             # 20  <- form feed
        "    pass\n"                                      # 21
        "    return None\n"                               # 22
    )

    # Same far-divergence shape as `form_feed.py`, with a vertical tab
    # instead of a form feed: N2's finding was that the fix detected only
    # "\x0c" and left the other eight splitlines-only-break characters
    # producing the identical hazard.
    vtab = repo / "vtab.py"
    vtab.write_text(
        "def charge(order):\n"                           # 1
        "    if order.already_charged:\n"                # 2
        "        return {'status': 'duplicate'}\n"       # 3  <- target
        "    order.mark_processed()\n"                   # 4
        "    return order.total\n"                       # 5
        "\n"                                             # 6
        "\n"                                             # 7
        "def refund(order):\n"                           # 8
        "    return -order.total\n"                       # 9
        "\n"                                             # 10
        "\n"                                             # 11
        "def audit_note():\n"                            # 12
        "    pass\n"                                      # 13
        "\n"                                             # 14
        "\n"                                             # 15
        "def another_helper():\n"                        # 16
        "    pass\n"                                      # 17
        "\n"                                             # 18
        "\n"                                             # 19
        "def report():\x0b\n"                             # 20  <- vertical tab
        "    pass\n"                                      # 21
        "    return None\n"                               # 22
    )

    korean = repo / "결제" / "수수료.py"
    korean.parent.mkdir(parents=True)
    korean.write_text(
        "import math\n"                                  # 1
        "\n"                                             # 2
        "\n"                                             # 3
        "def charge(order):\n"                           # 4
        "    if order.already_charged:\n"                # 5
        "        return {'status': 'duplicate'}\n"       # 6  <- target
        "    order.mark_processed()\n"                   # 7
        "    return order.total\n"                       # 8
    )

    sha = _commit(repo, "hotfix: prevent double charge (#4127)",
                  "2019-11-08T02:14:00")

    return {
        "repo": str(repo),
        "sha": sha,
        "python": {"path": "billing/fee.py", "start": 6, "end": 6,
                    "indent": "        "},
        "kotlin": {"path": "Fee.kt", "start": 6, "end": 6,
                    "indent": "            "},
        "reorder": {"path": "Ledger.kt", "start": 6, "end": 6,
                     "indent": "            "},
        "edge": {"path": "edge.py", "start": 4, "end": 4,
                  "indent": "        "},
        "sql": {"path": "migrations/0001_fee.sql", "start": 4, "end": 4,
                 "indent": "    "},
        "block": {"path": "block.py", "start": 5, "end": 8,
                   "indent": "    "},
        "head": {"path": "head.py", "start": 1, "end": 1, "indent": ""},
        "tail": {"path": "tail.py", "start": 3, "end": 3, "indent": "    "},
        "docs": {"path": "docs/fee.rst", "start": 4, "end": 4, "indent": ""},
        "binary": {"path": "blob.py", "start": 1, "end": 1, "indent": ""},
        "nul": {"path": "nul.py", "start": 2, "end": 2, "indent": "    "},
        "crlf": {"path": "crlf.py", "start": 6, "end": 6,
                  "indent": "        "},
        "form_feed": {"path": "form_feed.py", "start": 3, "end": 3,
                       "indent": "        "},
        "vtab": {"path": "vtab.py", "start": 3, "end": 3,
                  "indent": "        "},
        "korean": {"path": "결제/수수료.py", "start": 6, "end": 6,
                    "indent": "        "},
    }


def build_co_changed_cap(dest: str, *, name: str = "co_changed_cap") -> dict:
    """Two commits, for testing trace()'s co_changed cap and priority
    ordering (noise.is_test_path first, then the target's own directory,
    then everything else) against ground truth rather than against
    "however many paths happen to exist".

    `big_sha` changes the target file plus six other paths in one commit:
    one test file (`tests/payment_test.py`, nowhere near the target's own
    directory, so it can only rank first through is_test_path, not through
    directory proximity), two files beside the target
    (`billing/helper_one.py`, `billing/helper_two.py`), and three files in
    an unrelated directory (`other/far_one.py`, `other/far_two.py`,
    `other/far_three.py`) -- "far" meaning nothing here, deliberately, so a
    cap that dropped the test file or ranked a far file ahead of a
    same-directory one would have nothing plausible to justify it.

    `base_sha` changes the target file plus exactly one other path
    (`misc/base_helper.py`), fewer than any cap this fixture's tests use,
    to prove a commit that changes fewer paths than the cap is carried
    whole rather than clipped down to look like a capped one.

    Both shas are meant to be passed to trace()'s `include_commits`
    (a commit named that way is never noise-filtered and always kept, see
    trace.py), so this fixture does not need to construct a scenario where
    blame or pickaxe organically discovers either one; what the co_changed
    cap and priority ordering do with each commit's changed paths is the
    only thing under test.
    """
    repo = _init(dest, name)
    target = repo / "billing" / "payment.py"
    target.parent.mkdir(parents=True)
    base_other = repo / "misc" / "base_helper.py"
    base_other.parent.mkdir(parents=True)

    target.write_text("def charge(order):\n    return order.total\n")
    base_other.write_text("VALUE = 1\n")
    base_sha = _commit(repo, "feat: add payment module", "2020-01-01T10:00:00")

    test_file = repo / "tests" / "payment_test.py"
    test_file.parent.mkdir(parents=True)
    helper_one = repo / "billing" / "helper_one.py"
    helper_two = repo / "billing" / "helper_two.py"
    far_dir = repo / "other"
    far_dir.mkdir(parents=True)
    far_one = far_dir / "far_one.py"
    far_two = far_dir / "far_two.py"
    far_three = far_dir / "far_three.py"

    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return {'status': 'duplicate'}\n"
        "    return order.total\n"
    )
    test_file.write_text("def test_charge():\n    pass\n")
    helper_one.write_text("def helper_one():\n    pass\n")
    helper_two.write_text("def helper_two():\n    pass\n")
    far_one.write_text("X = 1\n")
    far_two.write_text("X = 2\n")
    far_three.write_text("X = 3\n")
    big_sha = _commit(repo, "fix: guard duplicate charge", "2020-02-01T10:00:00")

    return {
        "repo": str(repo),
        "path": "billing/payment.py",
        "line": 2,
        "base_sha": base_sha,
        "big_sha": big_sha,
        "test_path": "tests/payment_test.py",
        "same_dir_paths": ["billing/helper_one.py", "billing/helper_two.py"],
        "far_paths": ["other/far_one.py", "other/far_two.py", "other/far_three.py"],
        "base_other_path": "misc/base_helper.py",
        "big_total": 6,  # test + 2 same-dir + 3 far, target itself excluded
        "base_total": 1,  # base_other, target itself excluded
    }


def build_guard_name_collision(dest: str, *, name: str = "guard_name_collision") -> dict:
    """One commit that co-changes a `Test$` false positive ahead of a genuine
    test, alphabetically, alongside the target.

    Regression fixture for the final-review I1 finding: `noise.is_test_path`
    recognizes both `billing/ABTest.kt` (an A/B-experiment flag holder, not a
    test suite -- see that function's docstring for why the false positive
    is an accepted cost) and `tests/payment_test.py` (a genuine test) as
    test-looking paths. Git's own path order is alphabetical, so
    `ABTest.kt` sorts before `payment.py` sorts before `tests/...`, meaning
    `ABTest.kt` is first in `co_changed` and a guard line that only ever
    named the first match would name the false positive and never the real
    test that actually guards the target.
    """
    repo = _init(dest, name)
    billing = repo / "billing"
    billing.mkdir(parents=True)
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)

    false_positive = billing / "ABTest.kt"
    target = billing / "payment.py"
    test_file = tests_dir / "payment_test.py"

    false_positive.write_text("// A/B experiment flag holder, NOT a test suite\n")
    target.write_text("def charge(order):\n    return order.total\n")
    test_file.write_text("def test_charge_is_idempotent():\n    assert True\n")
    real_sha = _commit(repo, "hotfix: prevent double charge (#4127)", "2026-08-20T09:00:00")

    return {
        "repo": str(repo),
        "path": "billing/payment.py",
        "line": 1,
        "real_sha": real_sha,
        "false_positive_path": "billing/ABTest.kt",
        "test_path": "tests/payment_test.py",
    }


def build_guard_capped_test_paths(dest: str, *, name: str = "guard_capped_test_paths",
                                   n: int = 30) -> dict:
    """One commit touching the target plus `n` test-looking paths
    (`t/case_01_test.py` .. `t/case_{n}_test.py`), all sorting ahead of the
    target alphabetically and all recognized by `noise.is_test_path`.

    Regression fixture for final-rereview's N1: when `trace()`'s
    `max_co_changed` cap (passed by the caller, not this builder) is
    smaller than `n`, `co_changed` keeps only the top `max_co_changed` of
    these -- co-changed tests rank first in `_co_changed_priority`, so
    they fill the cap before any non-test path would -- while
    `co_changed_totals` still records the true count of every path this
    commit touched. `artifacts._guard_text`/`_guard_lines` must read that
    disclosed total (via `_co_changed_capped`) rather than trust
    `co_changed`'s already-capped length: the "and N more" tail describes
    a set this fixture makes far larger than what the cap lets through.
    """
    repo = _init(dest, name)
    target = repo / "app" / "service.py"
    target.parent.mkdir(parents=True)
    t_dir = repo / "t"
    t_dir.mkdir(parents=True)

    target.write_text("def charge(order):\n    return order.total\n")
    for i in range(1, n + 1):
        (t_dir / "case_{:02d}_test.py".format(i)).write_text(
            "def test_case_{:02d}():\n    assert True\n".format(i))
    target.write_text(
        "def charge(order):\n"
        "    if order.already_charged:\n"
        "        return {'status': 'duplicate'}\n"
        "    return order.total\n"
    )
    sha = _commit(repo, "hotfix: prevent double charge (#4127)", "2026-08-20T09:00:00")

    return {
        "repo": str(repo),
        "path": "app/service.py",
        "line": 2,
        "sha": sha,
        "test_paths": ["t/case_{:02d}_test.py".format(i) for i in range(1, n + 1)],
        "total_changed": n,  # test paths only, target itself excluded
    }
