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


def build_f1(dest: str) -> dict:
    """N1: a repo-wide formatter commit flips string-quote style, burying
    the real author of the target line.

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
    repo = _init(dest, "f1")
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
    real_sha = _commit(repo, "hotfix: prevent double charge (#4127)",
                       "2019-11-08T02:14:00")

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
    noise_sha = _commit(repo, "chore: apply formatter", "2023-06-01T09:00:00")

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
    corrupts `posixpath.split`, so `artifacts._is_test_path` can no longer
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
    # directory-segment path in `artifacts._is_test_path` rather than
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
