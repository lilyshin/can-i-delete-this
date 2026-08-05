"""Classify commits as historical debris (noise) so blame results can be
filtered. See noise-catalog.md for the catalog this implements.

Pure functions only. This module never touches git.
"""

import re
from dataclasses import dataclass

BREADTH_THRESHOLD = 20

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

_VENDOR_DIRS = ("vendor/", "third_party/", "thirdparty/", "node_modules/",
                "Pods/", "external/", "deps/")
_GENERATED_HINTS = ("_pb2.py", ".pb.go", "_generated.", ".gen.", "generated/",
                    ".g.dart", "_pb.js")


@dataclass(frozen=True)
class NoiseVerdict:
    is_noise: bool
    category: str
    confidence: float
    signals: tuple


def _all_paths_match(paths, needles):
    if not paths:
        return False
    return all(any(n in p for n in needles) for p in paths)


def score(commit, *, whitespace_only, paths, import_ratio=0.0):
    signals = []
    category = ""

    if commit.parents_count > 1:
        signals.append("merge commit (parents={})".format(commit.parents_count))
        category = "N9"

    if _all_paths_match(paths, _VENDOR_DIRS):
        signals.append("all paths vendored")
        category = "N6"
    elif _all_paths_match(paths, _GENERATED_HINTS) or _GENERATED.search(commit.subject):
        if _all_paths_match(paths, _GENERATED_HINTS):
            signals.append("all paths look generated")
            category = "N7"

    if whitespace_only:
        signals.append("diff is empty when whitespace is ignored")
        category = "N1"
    if _FORMATTER.search(commit.subject):
        signals.append("subject matches formatter vocabulary")
        category = "N1"
    if commit.files_changed >= BREADTH_THRESHOLD:
        signals.append("touches {} files".format(commit.files_changed))
        if category == "":
            category = "N1"

    if import_ratio >= 0.8 or _IMPORTS.search(commit.subject):
        signals.append("changes concentrated in import block")
        category = "N2"
    if _LICENSE.search(commit.subject):
        signals.append("subject mentions license or header")
        category = "N3"
    if _MOVE.search(commit.subject):
        signals.append("subject mentions move or rename")
        if category == "":
            category = "N5"
    if _UPGRADE.search(commit.subject):
        signals.append("subject mentions upgrade or migration")
        if category == "":
            category = "N8"
    if _TYPO.search(commit.subject):
        signals.append("subject mentions typo, comment or docs")
        if category == "":
            category = "N11"
    if _SQUASH_PR.search(commit.subject) and commit.files_changed >= BREADTH_THRESHOLD:
        signals.append("PR-title shaped subject over many files")
        category = "N10"

    is_noise = category != ""
    confidence = 0.0 if not is_noise else min(1.0, 0.4 + 0.2 * len(signals))
    return NoiseVerdict(is_noise, category, confidence, tuple(signals))
