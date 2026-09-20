"""Closed vocabularies for NSQ rows: failure classes, severity, user-facing copy.

The whole point of a closed enum is that the LLM normaliser cannot invent a
category the UI has no colour for. Anything unrecognised lands in OTHER.
"""
from __future__ import annotations

import re

FAILURE_CLASSES = (
    "ASSAY",
    "DISSOLUTION",
    "STERILITY",
    "ENDOTOXIN",
    "MICROBIAL",
    "PARTICULATE",
    "CONTAMINANT",
    "IDENTIFICATION",
    "DESCRIPTION",
    "PH",
    "SPURIOUS",
    "OTHER",
)

SEVERITY_BY_CLASS = {
    "SPURIOUS": "CRITICAL",
    "STERILITY": "CRITICAL",
    "ENDOTOXIN": "CRITICAL",
    "CONTAMINANT": "CRITICAL",
    "ASSAY": "HIGH",
    "DISSOLUTION": "HIGH",
    "IDENTIFICATION": "HIGH",
    "MICROBIAL": "MODERATE",
    "PARTICULATE": "MODERATE",
    "PH": "MODERATE",
    "DESCRIPTION": "LOW",
    "OTHER": "LOW",
}

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}

# Plain-language guidance. Deliberately never says "safe" and never says "stop
# your medication" without pointing at a clinician.
ADVICE = {
    "CRITICAL": {
        "en": "Stop taking this. Contact your doctor and the pharmacy you bought it from.",
        "hi": "\u0907\u0938\u0947 \u0932\u0947\u0928\u093e \u092c\u0902\u0926 \u0915\u0930\u0947\u0902\u0964 \u0905\u092a\u0928\u0947 \u0921\u0949\u0915\u094d\u091f\u0930 \u0914\u0930 \u092b\u093e\u0930\u094d\u092e\u0947\u0938\u0940 \u0938\u0947 \u0938\u0902\u092a\u0930\u094d\u0915 \u0915\u0930\u0947\u0902\u0964",
        "ta": "\u0b87\u0ba4\u0bc8 \u0b89\u0b9f\u0bcd\u0b95\u0bca\u0bb3\u0bcd\u0bb5\u0ba4\u0bc8 \u0ba8\u0bbf\u0bb1\u0bc1\u0ba4\u0bcd\u0ba4\u0bc1\u0b99\u0bcd\u0b95\u0bb3\u0bcd. \u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0bae\u0bb0\u0bc1\u0ba4\u0bcd\u0ba4\u0bc1\u0bb5\u0bb0\u0bc8\u0baf\u0bc1\u0bae\u0bcd \u0bae\u0bb0\u0bc1\u0ba8\u0bcd\u0ba4\u0b95\u0bae\u0bcd \u0b9a\u0bc6\u0bb2\u0bcd\u0bb2\u0bc8\u0baf\u0bc1\u0bae\u0bcd \u0ba4\u0bca\u0b9f\u0bb0\u0bcd\u0baa\u0bc1 \u0b95\u0bca\u0bb3\u0bcd\u0bb3\u0bc1\u0b99\u0bcd\u0b95\u0bb3\u0bcd.",
    },
    "HIGH": {
        "en": "This batch may be weaker than labelled. Speak to your doctor before your next dose.",
        "hi": "\u092f\u0939 \u092c\u0948\u091a \u0932\u0947\u092c\u0932 \u0938\u0947 \u0915\u092e\u091c\u094b\u0930 \u0939\u094b \u0938\u0915\u0924\u093e \u0939\u0948\u0964 \u0905\u0917\u0932\u0940 \u0916\u0941\u0930\u093e\u0915 \u0938\u0947 \u092a\u0939\u0932\u0947 \u0921\u0949\u0915\u094d\u091f\u0930 \u0938\u0947 \u092c\u093e\u0924 \u0915\u0930\u0947\u0902\u0964",
        "ta": "\u0b87\u0ba8\u0bcd\u0ba4 \u0ba4\u0bca\u0b95\u0bc1\u0ba4\u0bbf \u0bb2\u0bc7\u0baa\u0bbf\u0bb3\u0bbf\u0bb2\u0bcd \u0b95\u0bc2\u0bb1\u0bbf\u0baf\u0ba4\u0bc8\u0bb5\u0bbf\u0b9f \u0baa\u0bb2\u0bb5\u0bc0\u0ba9\u0bae\u0bbe\u0b95 \u0b87\u0bb0\u0bc1\u0b95\u0bcd\u0b95\u0bb2\u0bbe\u0bae\u0bcd. \u0b85\u0b9f\u0bc1\u0ba4\u0bcd\u0ba4 \u0bae\u0bb0\u0bc1\u0ba8\u0bcd\u0ba4\u0bc1\u0b95\u0bcd\u0b95\u0bc1 \u0bae\u0bc1\u0ba9\u0bcd \u0bae\u0bb0\u0bc1\u0ba4\u0bcd\u0ba4\u0bb0\u0bbf\u0b9f\u0bae\u0bcd \u0b95\u0bc7\u0b9f\u0bcd\u0b95\u0bb5\u0bc1\u0bae\u0bcd.",
    },
    "MODERATE": {
        "en": "This batch failed a quality test. Return it to the pharmacy.",
        "hi": "\u092f\u0939 \u092c\u0948\u091a \u0917\u0941\u0923\u0935\u0924\u094d\u0924\u093e \u092a\u0930\u0940\u0915\u094d\u0937\u0923 \u092e\u0947\u0902 \u0935\u093f\u092b\u0932 \u0930\u0939\u093e\u0964 \u0907\u0938\u0947 \u092b\u093e\u0930\u094d\u092e\u0947\u0938\u0940 \u0915\u094b \u0932\u094c\u091f\u093e \u0926\u0947\u0902\u0964",
        "ta": "\u0b87\u0ba8\u0bcd\u0ba4 \u0ba4\u0bca\u0b95\u0bc1\u0ba4\u0bbf \u0ba4\u0bb0\u0b9a\u0bcd\u0b9a\u0bcb\u0ba4\u0ba9\u0bc8\u0baf\u0bbf\u0bb2\u0bcd \u0ba4\u0bcb\u0bb2\u0bcd\u0bb5\u0bbf\u0baf\u0b9f\u0bc8\u0ba8\u0bcd\u0ba4\u0ba4\u0bc1. \u0bae\u0bb0\u0bc1\u0ba8\u0bcd\u0ba4\u0b95\u0ba4\u0bcd\u0ba4\u0bbf\u0b9f\u0bae\u0bcd \u0ba4\u0bbf\u0bb0\u0bc1\u0baa\u0bcd\u0baa\u0bbf \u0b95\u0bca\u0b9f\u0bc1\u0b95\u0bcd\u0b95\u0bb5\u0bc1\u0bae\u0bcd.",
    },
    "LOW": {
        "en": "A labelling or appearance standard was not met. Ask your pharmacist if you are unsure.",
        "hi": "\u0932\u0947\u092c\u0932\u093f\u0902\u0917 \u092f\u093e \u0926\u093f\u0916\u093e\u0935\u091f \u0915\u093e \u092e\u093e\u0928\u0915 \u092a\u0942\u0930\u093e \u0928\u0939\u0940\u0902 \u0939\u0941\u0906\u0964 \u0938\u0902\u0926\u0947\u0939 \u0939\u094b \u0924\u094b \u092b\u093e\u0930\u094d\u092e\u093e\u0938\u093f\u0938\u094d\u091f \u0938\u0947 \u092a\u0942\u091b\u0947\u0902\u0964",
        "ta": "\u0bb2\u0bc7\u0baa\u0bbf\u0bb3\u0bcd \u0b85\u0bb2\u0bcd\u0bb2\u0ba4\u0bc1 \u0ba4\u0bcb\u0bb1\u0bcd\u0bb1 \u0ba4\u0bb0\u0ba8\u0bbf\u0bb2\u0bc8 \u0b8e\u0b9f\u0bcd\u0b9f\u0baa\u0bcd\u0baa\u0b9f\u0bb5\u0bbf\u0bb2\u0bcd\u0bb2\u0bc8. \u0b9a\u0ba8\u0bcd\u0ba4\u0bc7\u0b95\u0bae\u0bcd \u0b8e\u0ba9\u0bbf\u0bb2\u0bcd \u0bae\u0bb0\u0bc1\u0ba8\u0bcd\u0ba4\u0bbe\u0bb3\u0bb0\u0bbf\u0b9f\u0bae\u0bcd \u0b95\u0bc7\u0b9f\u0bcd\u0b95\u0bb5\u0bc1\u0bae\u0bcd.",
    },
}

# Ordered: first pattern that hits wins, so put the specific ones first.
_CLASS_PATTERNS = (
    ("SPURIOUS", r"spurious|counterfeit|fake|misbrand|not\s+manufactur|adulterat"),
    ("STERILITY", r"steril"),
    ("ENDOTOXIN", r"endotoxin|pyrogen"),
    ("CONTAMINANT", r"heavy\s+metal|foreign\s+matter|cross[-\s]?contamin|contaminat|residual\s+solvent"),
    ("PARTICULATE", r"particulate|particle|clarity\s+of\s+solution|visible\s+particle"),
    ("MICROBIAL", r"microbial|microbiolog|bio\s?burden|bacterial\s+count|total\s+aerobic"),
    ("DISSOLUTION", r"dissolution|disintegrat|release\s+profile"),
    ("ASSAY", r"assay|content\s+of|drug\s+content|potency|active\s+ingredient|estimation"),
    ("IDENTIFICATION", r"identificat|identity"),
    ("PH", r"\bph\b|acidity|alkalinity"),
    ("DESCRIPTION", r"description|appearance|label(l)?ing|uniformity\s+of\s+weight|average\s+weight|friability|leak\s+test"),
)


def classify_failure(reason: str) -> str:
    """Map a free-text CDSCO failure reason onto the closed enum."""
    text = (reason or "").lower()
    for cls, pattern in _CLASS_PATTERNS:
        if re.search(pattern, text):
            return cls
    return "OTHER"


def severity_for(failure_class: str) -> str:
    return SEVERITY_BY_CLASS.get((failure_class or "").upper(), "LOW")


def advice_for(severity: str, lang: str = "en") -> str:
    block = ADVICE.get((severity or "").upper(), ADVICE["LOW"])
    return block.get(lang, block["en"])


def coerce_class(value: str) -> str:
    """Accept whatever the model returned; never let an unknown class through."""
    v = (value or "").strip().upper().replace(" ", "_")
    if v == "P_H":
        v = "PH"
    return v if v in FAILURE_CLASSES else "OTHER"
