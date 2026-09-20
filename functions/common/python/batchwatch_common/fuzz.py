"""String similarity with a hard guarantee: identical results with or without
rapidfuzz installed.

rapidfuzz is a compiled wheel and is used when present because it is ~100x
faster. The pure-Python fallback implements exactly the same two metrics
(Indel-based ratio, and token_set_ratio) so a Lambda without the layer, a
laptop without a compiler, and CI all agree. tests/test_fuzz.py asserts the two
implementations agree on a corpus of real batch codes.
"""
from __future__ import annotations

try:  # pragma: no cover - exercised by whichever path is installed
    from rapidfuzz.fuzz import ratio as _rf_ratio, token_set_ratio as _rf_token_set_ratio

    HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    HAVE_RAPIDFUZZ = False


def _lcs_len(a: str, b: str) -> int:
    """Length of the longest common subsequence (rolling-row DP)."""
    if not a or not b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        append = cur.append
        for j, cb in enumerate(b):
            append(prev[j] + 1 if ca == cb else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def _py_ratio(a: str, b: str) -> float:
    """Indel similarity in 0..100 — the same definition rapidfuzz.fuzz.ratio uses."""
    if not a and not b:
        return 100.0
    total = len(a) + len(b)
    if total == 0:
        return 100.0
    return 200.0 * _lcs_len(a, b) / total


def _tokens(s: str) -> list[str]:
    return sorted(set(s.lower().split()))


def _py_token_set_ratio(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta and not tb:
        return 100.0
    if not ta or not tb:
        return 0.0
    inter = sorted(ta & tb)
    d1 = sorted(ta - tb)
    d2 = sorted(tb - ta)
    s_inter = " ".join(inter)
    s1 = " ".join(inter + d1).strip()
    s2 = " ".join(inter + d2).strip()
    if s_inter and not d1 and not d2:
        return 100.0
    best = _py_ratio(s1, s2)
    if s_inter:
        best = max(best, _py_ratio(s_inter, s1), _py_ratio(s_inter, s2))
    return best


def ratio(a: str, b: str) -> float:
    """Similarity of two strings, 0..100."""
    a, b = a or "", b or ""
    if a == b:
        return 100.0
    if HAVE_RAPIDFUZZ:
        return float(_rf_ratio(a, b))
    return _py_ratio(a, b)


def token_set_ratio(a: str, b: str) -> float:
    """Order- and duplicate-insensitive similarity of two phrases, 0..100."""
    a, b = a or "", b or ""
    if HAVE_RAPIDFUZZ:
        return float(_rf_token_set_ratio(a, b))
    return _py_token_set_ratio(a, b)
