"""The pure-Python similarity fallback must agree with rapidfuzz exactly.

If it drifts, a Lambda without the compiled wheel would score differently from
CI, and the matching thresholds would mean two different things.
"""
import random
import string

import pytest

from batchwatch_common import fuzz

rapidfuzz = pytest.importorskip("rapidfuzz", reason="rapidfuzz not installed")


def _random_code(rng: random.Random) -> str:
    alphabet = string.ascii_uppercase + string.digits + "  "
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 18))).strip()


def test_pure_python_ratio_matches_rapidfuzz():
    rng = random.Random(7)
    for _ in range(2000):
        a, b = _random_code(rng), _random_code(rng)
        assert fuzz._py_ratio(a, b) == pytest.approx(rapidfuzz.fuzz.ratio(a, b), abs=1e-9)


def test_pure_python_token_set_ratio_matches_rapidfuzz():
    rng = random.Random(11)
    for _ in range(2000):
        a, b = _random_code(rng), _random_code(rng)
        assert fuzz._py_token_set_ratio(a, b) == pytest.approx(
            rapidfuzz.fuzz.token_set_ratio(a, b), abs=1e-9
        )


def test_real_drug_names_agree():
    pairs = [
        ("paracetamol 650mg", "paracetamol tablets ip 650mg"),
        ("vireon laboratories baddi", "vireon laboratories"),
        ("amoxycillin clavulanic acid", "clavulanic acid amoxycillin"),
        ("", "paracetamol"),
        ("metformin", "metformin"),
    ]
    for a, b in pairs:
        assert fuzz._py_ratio(a, b) == pytest.approx(rapidfuzz.fuzz.ratio(a, b), abs=1e-9)
        assert fuzz._py_token_set_ratio(a, b) == pytest.approx(
            rapidfuzz.fuzz.token_set_ratio(a, b), abs=1e-9
        )


def test_public_helpers_are_bounded():
    assert fuzz.ratio("abc", "abc") == 100.0
    assert fuzz.ratio("", "") == 100.0
    assert 0.0 <= fuzz.ratio("abc", "xyz") <= 100.0
    assert fuzz.token_set_ratio("a b", "b a") == 100.0
