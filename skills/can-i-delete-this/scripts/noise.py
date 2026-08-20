"""Classify commits as historical debris (noise) so blame results can be
filtered. See noise-catalog.md for the catalog this implements.

Pure functions only. This module never touches git.

**A commit is filtered on what it changed, never on how its author
described it.** A subject line is a description of a change, written in
whatever language its author speaks, under whatever convention (or none)
their repository follows. Reading it to decide whether a commit is debris
made this classifier work in English and fail in every other language, and
fail again in any repository that does not write `chore:` prefixes. Worse,
it filtered in the dangerous direction: `refactor: extract net helpers`
across twenty files was discarded on the word "extract" alone, and if that
commit was the real introduction, nothing downstream could recover it.

So the split here is:

- **Signals** are computed from the diff, the paths, and the commit graph.
  Only these set `is_noise`, and only these remove a candidate.
- **Hints** are vocabulary matches on the subject. They are reported for
  the agent to weigh (it reads every subject itself, in any language) and
  they never filter anything.

The asymmetry that decides every close call: leaving debris in the
candidate list costs the agent one extra read, while discarding the real
introducing commit is unrecoverable.
"""

import posixpath
import re
from dataclasses import dataclass, field

BREADTH_THRESHOLD = 20

# Per-file churn at or below this, across a commit wider than
# BREADTH_THRESHOLD, is the shape of a mechanical sweep (one or two lines
# rewritten the same way everywhere). It is reported as a hint and never
# filters: a security fix applied to twenty-five call sites has exactly
# this shape too, and that commit is the answer, not debris.
SWEEP_CHURN_PER_FILE = 2.0

_FORMATTER = re.compile(
    r"\b(fmt|format|formatting|formatter|prettier|lint|linting|style|styling"
    r"|gofmt|rustfmt|black|clang-format|mix format|reindent|whitespace)\b", re.I)
_LICENSE = re.compile(r"\b(licen[cs]e|copyright|header|spdx)\b", re.I)
_IMPORTS = re.compile(r"\b(imports?|includes?|use statements|isort|goimports)\b", re.I)
_GENERATED = re.compile(r"\b(generated|codegen|regenerate|proto|protobuf|swagger|openapi)\b", re.I)
_UPGRADE = re.compile(r"\b(upgrade|bump|migrate to|port to|modernize|deprecat)\b", re.I)
_TYPO = re.compile(r"\b(typo|typos|comment|comments|wording|spelling|docs?)\b", re.I)
_MOVE = re.compile(r"\b(move|moved|relocate|reorganiz|restructur|rename|extract)\b", re.I)
_SQUASH_PR = re.compile(r"\(#\d+\)\s*$")

_HINT_PATTERNS = (
    (_FORMATTER, "subject matches formatter vocabulary (English)"),
    (_LICENSE, "subject mentions license or header (English)"),
    (_IMPORTS, "subject mentions imports (English)"),
    (_GENERATED, "subject mentions generated code (English)"),
    (_MOVE, "subject mentions move or rename (English)"),
    (_UPGRADE, "subject mentions upgrade or migration (English)"),
    (_TYPO, "subject mentions typo, comment or docs (English)"),
)

_VENDOR_DIRS = ("vendor/", "third_party/", "thirdparty/", "node_modules/",
                "Pods/", "external/", "deps/")
_GENERATED_HINTS = ("_pb2.py", ".pb.go", "_generated.", ".gen.", "generated/",
                    ".g.dart", "_pb.js")

# Directory names that mark everything under them as test code, used by
# is_test_path below.
_TEST_DIR_NAMES = {"tests", "test", "spec", "specs", "__tests__"}

# A literal, capitalized "Test" ending, the Android/JVM convention for
# both directories ("androidTest/") and class-per-file names
# ("FooTest.kt"). Case sensitivity alone does the whole job: "contest",
# "latest", "protest" and "Manifest" all end in the same four letters but
# never capitalize the T, so they never match this pattern regardless of
# what comes before it. An earlier version of this pattern also required
# the character just before "Test" to be lowercase, a digit or an
# underscore (i.e. `[a-z0-9_]Test$`), on the theory that a real word
# boundary looks like "fooTest". That extra condition rejected exactly the
# two-letter-acronym test names real JVM/Android code actually uses --
# "IOTest.java", "HTTPTest.kt", "JSONTest.java", "TTest.java" -- because
# the letter immediately before "Test" there is itself a capital, so it
# never matched `[a-z0-9_]`. See is_test_path's docstring for why that
# false-negative direction, not the false-positive one, is the cost worth
# avoiding.
_CAMEL_TEST_SUFFIX = re.compile(r"Test$")

# Quote characters unified by every formatter that rewrites tokens rather
# than whitespace, which is the class `git blame -w` cannot see through
# and this project exists for.
_QUOTES = str.maketrans({"'": "\x00", '"': "\x00", "`": "\x00"})
_TRAILING_PUNCT = re.compile(r"[,;]+\s*$")
_WS_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class NoiseVerdict:
    is_noise: bool
    category: str
    confidence: float
    signals: tuple
    # Vocabulary observations. Never filter; carried so the agent (which
    # reads subjects in any language) can weigh them alongside the diff.
    hints: tuple = field(default=())


def _all_paths_match(paths, needles):
    if not paths:
        return False
    return all(any(n in p for n in needles) for p in paths)


def is_test_path(path):
    """Identify test files by filename/directory convention, not substring match.

    Recognises:
      - any directory segment named tests/test/spec/specs/__tests__
      - filename stems starting with "test_" or ending with "_test"/"_spec"
      - a ".test." or ".spec." segment before the final extension
        (e.g. "foo.test.js", "foo.spec.ts")
      - a directory or filename stem ending in the literal, capitalized
        word "Test" (e.g. "androidTest/", "FooTest.kt", "IOTest.java",
        "TTest.java", bare "Test.kt"), the Android/JVM convention where the
        word boundary is a capital letter rather than a separator

    Deliberately does NOT match a bare "test"/"spec" substring anywhere in the
    path, which would misclassify files like "latest.py", "contest.py",
    "inspector.py", "specification.md" or "respect.go" as tests: the "Test"
    check above is case-sensitive specifically so "contest", "latest",
    "protest" and "Manifest" -- which end in the same four letters but
    never capitalize the T -- stay false.

    That check carries no other condition on what precedes "Test": it
    matches "ABTest.kt" (an A/B-test feature class, not a test suite) just
    as readily as "FooTest.kt". That is an accepted, deliberate cost, not
    an oversight -- see _CAMEL_TEST_SUFFIX's own comment for the false
    positives an earlier, narrower version of this pattern let through
    instead. The asymmetry this module is built on (see the module
    docstring) is why the trade is made in this direction: a false
    positive here costs a reader one extra file open to see that
    "ABTest.kt" is not actually a test; a false negative silently drops a
    real co-changed test out of trace.py's tier-0 priority (see
    trace._co_changed_priority) and tells an agent "no test guards this"
    about a target a test genuinely does guard. The first costs a minute;
    the second is the wrong-direction, unrecoverable failure this whole
    module exists to avoid.

    This lives here, in the one module with no git and no filesystem access,
    rather than in artifacts.py (where it originated) or trace.py, because
    both now need the identical judgement on the identical kind of value: a
    bare path string, nothing else. artifacts.py uses it to find the test
    that guards a candidate; trace.py uses it to decide which of a commit's
    co-changed paths are worth keeping when there are more than the cap
    allows. A path is a path regardless of which caller is asking, so one
    classifier here is what keeps both callers' answers from drifting apart,
    the same reason _VENDOR_DIRS and _GENERATED_HINTS live here instead of
    being duplicated at each call site.
    """
    if not path:
        return False

    dirname, filename = posixpath.split(path)
    dir_parts = [p for p in dirname.split("/") if p]
    for part in dir_parts:
        if part.lower() in _TEST_DIR_NAMES or _CAMEL_TEST_SUFFIX.search(part):
            return True

    raw_stem = filename.split(".")[0]
    lowered_segments = filename.lower().split(".")
    lowered_stem = lowered_segments[0]
    middle = lowered_segments[1:-1]  # segments between the stem and the final extension
    if "test" in middle or "spec" in middle:
        return True

    if (lowered_stem.startswith("test_") or lowered_stem.endswith("_test")
            or lowered_stem.endswith("_spec")):
        return True

    if _CAMEL_TEST_SUFFIX.search(raw_stem):
        return True

    return False


def normalize_code_line(line):
    """Strip the differences a formatter creates and a reader does not care
    about: indentation and internal spacing, quote character, and trailing
    commas or semicolons.

    Deliberately not a parser. It equates `x = 'a'` with `x = "a"` and
    leaves `x = 'a'` distinct from `x = 'b'`, which is the whole judgement
    being made.
    """
    s = line.translate(_QUOTES)
    s = _WS_RUN.sub(" ", s).strip()
    return _TRAILING_PUNCT.sub("", s)


def is_cosmetic(removed, added):
    """True when every changed line is the same line with its formatting
    rewritten.

    Pairwise and in order, not as two sets: reordering statements leaves
    the multiset of lines identical while changing what the code does, so
    a set comparison would call a reordering cosmetic and discard it. An
    unequal number of removed and added lines is never cosmetic either,
    since something was genuinely added or deleted.

    An empty diff returns False. Nothing was observed, and "no evidence"
    must not read as "evidence of debris".
    """
    if not removed or len(removed) != len(added):
        return False
    norm_removed = [normalize_code_line(x) for x in removed]
    norm_added = [normalize_code_line(x) for x in added]
    if norm_removed == norm_added:
        # Identical after normalization, and something differed before it,
        # or git would not have reported these lines at all.
        return any(r != a for r, a in zip(removed, added))
    return False


def _rename_shape(commit):
    """True when git reported every changed path as a rename or copy and
    no line content changed: a pure move.

    `" => "` is git's own rename notation in `--numstat` output, so this
    needs no extra invocation and no vocabulary.
    """
    if not commit.churn:
        return False
    renamed = 0
    for added, removed, path in commit.churn:
        if " => " not in path:
            return False
        if added or removed:
            return False
        renamed += 1
    return renamed > 0


def _sweep_shape(commit):
    """The shape of a mechanical broad edit: wide, and shallow in every
    file it touches."""
    if commit.files_changed < BREADTH_THRESHOLD or not commit.churn:
        return False
    per_file = []
    for added, removed, _ in commit.churn:
        if added is None or removed is None:
            return False  # binary file; no line churn to reason about
        per_file.append(added + removed)
    if not per_file:
        return False
    return sum(per_file) / float(len(per_file)) <= SWEEP_CHURN_PER_FILE * 2


def score(commit, *, whitespace_only, paths, import_ratio=0.0,
          diff_lines=None):
    """Classify one commit.

    `diff_lines` is an optional `(removed, added)` pair from
    `gitq.diff_lines`, scoped to the path under investigation. When it is
    absent, the cosmetic check is simply not run; its absence never
    counts as evidence either way.
    """
    signals = []
    hints = []
    category = ""
    confidence = 0.0

    def claim(cat, conf):
        nonlocal category, confidence
        if category == "":
            category = cat
            confidence = conf

    # Evidence: the commit graph, the paths, the diff. No text is read
    # below, so every one of these behaves identically whatever language
    # the commit message is written in, or whether it has one at all.

    if commit.parents_count > 1:
        signals.append("merge commit (parents={})".format(commit.parents_count))
        claim("N9", 0.95)

    if _all_paths_match(paths, _VENDOR_DIRS):
        signals.append("all paths vendored")
        claim("N6", 0.95)

    if _all_paths_match(paths, _GENERATED_HINTS):
        signals.append("all paths look generated")
        claim("N7", 0.95)

    if whitespace_only:
        signals.append("diff is empty when whitespace is ignored")
        claim("N1", 0.95)

    if diff_lines and is_cosmetic(diff_lines[0], diff_lines[1]):
        signals.append(
            "every changed line is identical once quotes, spacing and "
            "trailing punctuation are normalized")
        claim("N1", 0.9)

    if import_ratio >= 0.8:
        signals.append("changes concentrated in import block")
        claim("N2", 0.95)

    if _rename_shape(commit):
        signals.append("git reports every path renamed with no line changes")
        claim("N5", 0.9)

    is_noise = category != ""
    if not is_noise:
        confidence = 0.0

    # Hints: read the subject, decide nothing. A hint may corroborate a
    # signal for a reader, and on its own it is just a claim the commit
    # makes about itself.

    if _sweep_shape(commit):
        hints.append("wide and shallow: {} files, {:.1f} lines changed per "
                     "file on average".format(
                         commit.files_changed,
                         (commit.insertions + commit.deletions)
                         / float(commit.files_changed)))

    for pattern, label in _HINT_PATTERNS:
        if pattern.search(commit.subject):
            hints.append(label)

    if _SQUASH_PR.search(commit.subject) and commit.files_changed >= BREADTH_THRESHOLD:
        hints.append(
            "PR-title shaped subject over {} files: the subject may name "
            "the pull request rather than this change".format(
                commit.files_changed))

    return NoiseVerdict(is_noise, category, confidence, tuple(signals),
                        tuple(hints))
