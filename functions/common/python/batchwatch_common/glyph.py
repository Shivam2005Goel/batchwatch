"""What foil-print OCR actually gets wrong, in two tiers.

Tier 1 - HARD_CONFUSABLE: glyph pairs that are genuinely indistinguishable on
embossed foil at phone-camera resolution. These are collapsed outright by
normalise.skeleton(), so the error disappears before scoring.

Tier 2 - SOFT_CONFUSABLE: pairs that are similar but still separable in good
light. Collapsing these too would start merging unrelated batch codes, so
instead they are charged a reduced edit cost (0.3 of a normal substitution)
inside ocr_similarity().

Modelling the error channel this way is what lifts recall on damaged reads
without spending any precision: a random substitution still costs full price.
"""
from __future__ import annotations

from functools import lru_cache

# Tier 1: collapsed in the skeleton. Digits win, so the skeleton is stable.
HARD_CONFUSABLE = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "S": "5",
    "B": "8",
    "Z": "2",
    "G": "6",
}

# Tier 2: charged a reduced substitution cost. Written as unordered pairs.
_SOFT_PAIRS = (
    ("4", "A"),
    ("7", "T"),
    ("7", "1"),
    ("7", "2"),
    ("9", "6"),
    ("9", "4"),
    ("U", "V"),
    ("V", "Y"),
    ("V", "W"),
    ("K", "X"),
    ("M", "N"),
    ("N", "H"),
    ("E", "F"),
    ("C", "6"),
    ("C", "0"),
    ("3", "8"),
    ("5", "6"),
    ("J", "1"),
    ("R", "P"),
    ("P", "F"),
    ("0", "8"),
    ("1", "4"),
)

SOFT_COST = 0.3

SOFT_CONFUSABLE: set[frozenset[str]] = {frozenset(p) for p in _SOFT_PAIRS}


def sub_cost(a: str, b: str) -> float:
    """Cost of reading `a` where `b` was printed."""
    if a == b:
        return 0.0
    return SOFT_COST if frozenset((a, b)) in SOFT_CONFUSABLE else 1.0


@lru_cache(maxsize=100_000)
def ocr_distance(a: str, b: str) -> float:
    """Levenshtein distance with OCR-aware substitution costs."""
    if a == b:
        return 0.0
    if not a:
        return float(len(b))
    if not b:
        return float(len(a))

    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, start=1):
        cur = [float(i)]
        for j, cb in enumerate(b, start=1):
            cur.append(
                min(
                    prev[j] + 1.0,                      # deletion
                    cur[j - 1] + 1.0,                   # insertion
                    prev[j - 1] + sub_cost(ca, cb),     # substitution
                )
            )
        prev = cur
    return prev[-1]


def ocr_similarity(a: str, b: str) -> float:
    """0..1 similarity of two batch codes under the OCR error model."""
    a, b = a or "", b or ""
    if a == b:
        return 1.0 if a else 0.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 0.0
    return max(0.0, 1.0 - ocr_distance(a, b) / longest)
