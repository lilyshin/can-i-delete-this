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
    confidence = 0.0

    # Stage 1: Structural signals (high confidence, standalone classification)
    # Collect all signals; set category only once (never override).

    if commit.parents_count > 1:
        signals.append("merge commit (parents={})".format(commit.parents_count))
        if category == "":
            category = "N9"
            confidence = 0.95

    if _all_paths_match(paths, _VENDOR_DIRS):
        signals.append("all paths vendored")
        if category == "":
            category = "N6"
            confidence = 0.95

    if _all_paths_match(paths, _GENERATED_HINTS):
        signals.append("all paths look generated")
        if category == "":
            category = "N7"
            confidence = 0.95

    if whitespace_only:
        signals.append("diff is empty when whitespace is ignored")
        if category == "":
            category = "N1"
            confidence = 0.95

    if import_ratio >= 0.8:
        signals.append("changes concentrated in import block")
        if category == "":
            category = "N2"
            confidence = 0.95

    # Stage 2: Keywords (lower confidence, require breadth threshold)
    # Only claim category if stage 1 didn't, but collect all signals regardless.

    if commit.files_changed >= BREADTH_THRESHOLD:
        if _FORMATTER.search(commit.subject):
            signals.append("subject matches formatter vocabulary")
            if category == "":
                category = "N1"
                confidence = 0.65

        if _LICENSE.search(commit.subject):
            signals.append("subject mentions license or header")
            if category == "":
                category = "N3"
                confidence = 0.65

        if _IMPORTS.search(commit.subject):
            signals.append("subject mentions imports")
            if category == "":
                category = "N2"
                confidence = 0.65

        if _GENERATED.search(commit.subject):
            signals.append("subject mentions generated code")
            if category == "":
                category = "N7"
                confidence = 0.65

        if _MOVE.search(commit.subject):
            signals.append("subject mentions move or rename")
            if category == "":
                category = "N5"
                confidence = 0.65

        if _UPGRADE.search(commit.subject):
            signals.append("subject mentions upgrade or migration")
            if category == "":
                category = "N8"
                confidence = 0.65

        if _TYPO.search(commit.subject):
            signals.append("subject mentions typo, comment or docs")
            if category == "":
                category = "N11"
                confidence = 0.65

        if _SQUASH_PR.search(commit.subject):
            signals.append("PR-title shaped subject over many files")
            if category == "":
                category = "N10"
                confidence = 0.65

    is_noise = category != ""
    if not is_noise:
        confidence = 0.0
    return NoiseVerdict(is_noise, category, confidence, tuple(signals))
