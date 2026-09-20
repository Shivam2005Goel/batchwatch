"""A model of how phone OCR damages a batch code printed on foil.

Used by the matcher tests instead of hand-typed corruptions so the regression
suite covers hundreds of cases rather than twenty. The damage classes and their
relative frequencies are the ones the engine is designed around:

  40%  hard-confusable glyph   (0/O, 1/I, 5/S ...)  - absorbed by the skeleton
  40%  soft-confusable glyph   (4/A, 7/T, U/V ...)  - charged a reduced cost
   8%  dropped character       (curved foil edge)
   8%  inserted character      (speckle read as a glyph)
   4%  unrelated substitution  (genuine misread)

plus label noise: a printed prefix, and a stray space or hyphen inside the code.
"""
from __future__ import annotations

import random

# Digit -> the letters it gets misread as. Inverse of glyph.HARD_CONFUSABLE.
HARD_INVERSE = {"0": "OQD", "1": "IL", "5": "S", "8": "B", "2": "Z", "6": "G"}

SOFT_INVERSE = {
    "4": "A9", "A": "4", "7": "T12", "T": "7", "9": "64", "U": "V",
    "V": "UYW", "K": "X", "X": "K", "M": "N", "N": "MH", "H": "N",
    "E": "F", "F": "EP", "C": "60", "3": "8", "J": "1", "R": "P", "P": "RF",
}

ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

PREFIXES = ("B.No. ", "BATCH NO: ", "B/N ", "LOT ", "B.NO.", "Batch No ")


def corrupt(code: str, rng: random.Random, errors: int = 1, label_noise: bool = True) -> str:
    """Apply `errors` OCR-shaped mutations to a batch code."""
    chars = list(code)
    applied = 0
    guard = 0
    while applied < errors and guard < 40:
        guard += 1
        if not chars:
            break
        i = rng.randrange(len(chars))
        c = chars[i]
        roll = rng.random()
        if roll < 0.40 and c in HARD_INVERSE:
            chars[i] = rng.choice(HARD_INVERSE[c])
            applied += 1
        elif roll < 0.80 and c in SOFT_INVERSE:
            chars[i] = rng.choice(SOFT_INVERSE[c])
            applied += 1
        elif roll < 0.88 and len(chars) > 4:
            chars.pop(i)
            applied += 1
        elif roll < 0.96:
            chars.insert(i, rng.choice(ALPHABET))
            applied += 1
        else:
            chars[i] = rng.choice(ALPHABET)
            applied += 1

    out = "".join(chars)
    if label_noise:
        if rng.random() < 0.4:
            out = rng.choice(PREFIXES) + out
        if rng.random() < 0.3 and len(out) > 2:
            j = rng.randrange(1, len(out))
            out = out[:j] + rng.choice("- ") + out[j:]
    return out


def unlisted_batch(rng: random.Random, known_skeletons: set[str]) -> str:
    """A batch code shaped like a real one but absent from the corpus."""
    from batchwatch_common.normalise import skeleton

    while True:
        code = (
            "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2))
            + str(rng.randint(1000, 9999))
            + rng.choice("ABCEHJKLMPRSTVWX")
        )
        if skeleton(code) not in known_skeletons:
            return code
