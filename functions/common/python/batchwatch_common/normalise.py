"""Turning messy real-world strings into things that compare.

This module is imported by BOTH the scan path (a photo from a phone) and the
fan-out path (a table from the regulator). If the two ever disagree about what
skeleton a batch code produces, the reverse lookup silently returns nothing.
That is why there is exactly one implementation and it lives in the layer.
"""
from __future__ import annotations

import re
from datetime import date

from .glyph import HARD_CONFUSABLE as CONFUSABLE
from .schema import classify_failure, coerce_class, severity_for

# ---------------------------------------------------------------- batch codes

# Unambiguous label words may butt straight up against the code ("B.NO.KP4021").
# Ambiguous two-letter ones must be followed by punctuation or space, because
# "BN12345" and "LT56667" are real batch codes, not labelled ones.
BATCH_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:B\.?\s*NO\.?|BATCH\s*(?:NO\.?|NUMBER)?|LOT\s*(?:NO\.?)?)\s*[:.\-]?\s*"
    r"|(?:BN|B\s*/\s*N|L\.?\s*N\.?)\s*(?:[:.\-]\s*|\s+)"
    r")",
    re.IGNORECASE,
)

# Prefixes that survive de-punctuation and must be peeled off the collapsed
# form too. OCR routinely splits or hyphenates the label word ("BA TCH NO:",
# "B.N-o."), which defeats the punctuation-aware regex above and would
# otherwise weld BATCHNO onto the front of the code.
#
# Only unambiguously-long tokens are listed. "BN" and "LT" are deliberately
# absent: real batch codes begin with them, and stripping those would corrupt
# more codes than it repairs. They are still handled by BATCH_PREFIX_RE when
# the printed label separates them with punctuation or a space.
_COLLAPSED_PREFIXES = (
    "BATCHNUMBER",
    "BATCHNO",
    "BATCH",
    "LOTNUMBER",
    "LOTNO",
    "LOT",
    "BNO",
)

# The hard-collapse map lives in glyph.py alongside the soft-confusable costs,
# re-exported here because both the scan path and the ingest path import it
# from this module.


def norm_batch(raw: str) -> str:
    """Strip label prefixes and every non-alphanumeric character.

    norm_batch("B.No. KP-4021-H") == "KP4021H"
    norm_batch("BA TCH NO: A0D629") == "A0D629"
    """
    if not raw:
        return ""
    s = str(raw).upper().strip()

    def keeps_a_code(rest: str) -> bool:
        """Only peel a prefix if what is left still looks like a batch code."""
        alnum = re.sub(r"[^A-Z0-9]", "", rest)
        return 3 <= len(alnum) <= 24 and any(c.isdigit() for c in alnum)

    # Some strips print the label twice ("BATCH NO: B.N. X"). Peel repeatedly.
    for _ in range(3):
        stripped = BATCH_PREFIX_RE.sub("", s, count=1).strip()
        if stripped == s or not keeps_a_code(stripped):
            break
        s = stripped

    s = re.sub(r"[^A-Z0-9]", "", s)

    # Second pass on the collapsed form: OCR that splits the label word
    # ("BA TCH NO:") gets past the punctuation-aware regex above.
    for _ in range(2):
        for prefix in _COLLAPSED_PREFIXES:
            if s.startswith(prefix) and keeps_a_code(s[len(prefix) :]):
                s = s[len(prefix) :]
                break
        else:
            break
    return s


def skeleton(value: str) -> str:
    """Collapse glyph-confusable characters so OCR noise stops mattering.

    Accepts either a raw label fragment or an already-normalised code.
    """
    return "".join(CONFUSABLE.get(c, c) for c in norm_batch(value))


def batch_keys(raw: str) -> tuple[str, str]:
    """(batch_norm, batch_skeleton) - always derive the pair together."""
    n = norm_batch(raw)
    return n, "".join(CONFUSABLE.get(c, c) for c in n)


def plausible_batch(code: str) -> bool:
    """Cheap sanity gate: batch codes run 3-20 chars and contain a digit."""
    c = norm_batch(code)
    return 3 <= len(c) <= 20 and any(ch.isdigit() for ch in c)


# ------------------------------------------------------------- manufacturers

_LEGAL_TOKENS = {
    "ms", "mfd", "mfg", "by", "at", "the",
    "ltd", "limited", "pvt", "private", "plc", "llp", "inc", "co", "company",
    "corp", "corporation", "unit", "units", "division", "div", "works", "factory",
    "india", "indian",
}


def norm_manufacturer(raw: str) -> str:
    """Lowercase, de-punctuate and drop legal-form noise words.

    Geography stays (it disambiguates same-name units) but the legal wrapper
    goes, so "M/s Nestor Pharmaceuticals Ltd., Faridabad" becomes
    "nestor pharmaceuticals faridabad".
    """
    if not raw:
        return ""
    s = str(raw).lower()
    s = re.sub(r"\bm\s*/\s*s\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _LEGAL_TOKENS and not t.isdigit()]
    return " ".join(tokens).strip()


# --------------------------------------------------------------- drug names

_DOSAGE_FORMS = {
    "tablets", "tablet", "tabs", "tab", "capsules", "capsule", "caps", "cap",
    "injection", "injections", "inj", "syrup", "suspension", "solution", "drops",
    "ointment", "cream", "gel", "powder", "granules", "sachet", "infusion",
    "eye", "ear", "oral", "topical", "film", "coated", "dispersible", "extended",
    "release", "sr", "er", "xr", "ip", "bp", "usp", "and", "for",
}

STRENGTH_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mcg|mg|gm|g|ml|iu|%|w/v|w/w)\b", re.IGNORECASE
)


def parse_strength(raw: str) -> str:
    """"Paracetamol Tablets IP 650mg" -> "650mg". Combinations join with "+"."""
    if not raw:
        return ""
    out = []
    for value, unit in STRENGTH_RE.findall(str(raw)):
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        out.append(f"{value}{unit.lower()}")
    return "+".join(out)


def norm_generic(raw: str) -> str:
    """Reduce a label string to its comparable core.

    "Paracetamol Tablets IP 650mg" -> "paracetamol"
    """
    if not raw:
        return ""
    s = str(raw).lower()
    s = STRENGTH_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9+]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _DOSAGE_FORMS and len(t) > 1]
    return " ".join(tokens).strip()


def drug_key(name: str) -> str:
    """The string the matcher compares: generic plus strength."""
    return " ".join(x for x in (norm_generic(name), parse_strength(name)) if x).strip()


# -------------------------------------------------------------------- dates

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_PATTERNS = (
    # MAR 2026 / MARCH-26 / SEPT.26  (checked first: month names are unambiguous)
    re.compile(
        r"\b(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*[-/ ]?\s*(?P<y>\d{2}|(?:19|20)\d{2})\b",
        re.IGNORECASE,
    ),
    # 2026-03 / 2026/03
    re.compile(r"\b(?P<y>(?:19|20)\d{2})[-/.](?P<m>0?[1-9]|1[0-2])\b"),
    # 15/03/2026 or 15-03-26 (day first, Indian convention)
    re.compile(
        r"\b(?:0?[1-9]|[12]\d|3[01])[-/.](?P<m>0?[1-9]|1[0-2])[-/.](?P<y>\d{2}|(?:19|20)\d{2})\b"
    ),
    # 03/2026, 3-2026, 03.2026
    re.compile(r"\b(?P<m>0?[1-9]|1[0-2])[-/.](?P<y>(?:19|20)\d{2})\b"),
    # 03/26 or 03-26
    re.compile(r"\b(?P<m>0[1-9]|1[0-2])[-/.](?P<y>\d{2})\b"),
    # 032026 printed with no separator
    re.compile(r"\b(?P<m>0[1-9]|1[0-2])(?P<y>(?:19|20)\d{2})\b"),
)


def _yyyy(y: str) -> int:
    n = int(y)
    return n if n > 100 else 2000 + n


def parse_month(raw: str) -> str:
    """Any plausible Indian pharma date string -> "YYYY-MM", else ""."""
    if not raw:
        return ""
    s = str(raw).strip()
    for pattern in _DATE_PATTERNS:
        m = pattern.search(s)
        if not m:
            continue
        groups = m.groupdict()
        month = _MONTHS[groups["mon"][:3].lower()] if groups.get("mon") else int(groups["m"])
        year = _yyyy(groups["y"])
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}"
    return ""


def month_delta(a: str, b: str) -> int | None:
    """Whole months between two "YYYY-MM" strings, or None if either is absent."""
    if not a or not b:
        return None
    try:
        ya, ma = (int(x) for x in a.split("-")[:2])
        yb, mb = (int(x) for x in b.split("-")[:2])
    except (ValueError, TypeError):
        return None
    return abs((ya * 12 + ma) - (yb * 12 + mb))


def is_expired(exp_month: str, today: date | None = None) -> bool:
    """True if the labelled expiry month is already behind us."""
    if not exp_month:
        return False
    today = today or date.today()
    try:
        y, m = (int(x) for x in exp_month.split("-")[:2])
    except (ValueError, TypeError):
        return False
    return (y, m) < (today.year, today.month)


# --------------------------------------------------------- canonical NSQ row


def canonical_row(raw: dict) -> dict:
    """Build the canonical NSQ record that gets written to DynamoDB.

    Accepts the loose dict produced by the LLM normaliser (or by the heuristic
    fallback) and fills in every derived field. Idempotent: feeding a canonical
    row back through produces the same row.
    """
    drug_name = (raw.get("drug_name") or "").strip()
    manufacturer_raw = (raw.get("manufacturer_raw") or raw.get("manufacturer") or "").strip()
    batch_raw = (raw.get("batch_raw") or raw.get("batch") or raw.get("batch_norm") or "").strip()
    batch_norm, batch_skel = batch_keys(batch_raw)

    reason = (raw.get("failure_reason") or "").strip()
    failure_class = coerce_class(raw.get("failure_class") or "")
    if failure_class == "OTHER":
        failure_class = classify_failure(reason)

    return {
        "drug_name": drug_name,
        "generic": raw.get("generic") or norm_generic(drug_name),
        "strength": raw.get("strength") or parse_strength(drug_name),
        "manufacturer_raw": manufacturer_raw,
        "manufacturer": norm_manufacturer(raw.get("manufacturer") or manufacturer_raw),
        "batch_raw": batch_raw,
        "batch_norm": batch_norm,
        "batch_skeleton": batch_skel,
        "mfg_date": parse_month(raw.get("mfg_date")),
        "exp_date": parse_month(raw.get("exp_date")),
        "failure_reason": reason,
        "failure_class": failure_class,
        "severity": raw.get("severity_override") or severity_for(failure_class),
        "lab": (raw.get("lab") or "").strip(),
        "alert_month": parse_month(raw.get("alert_month")) or (raw.get("alert_month") or ""),
        "source_url": raw.get("source_url") or "",
        "synthetic": bool(raw.get("synthetic", False)),
    }


def row_is_usable(row: dict) -> bool:
    """A row without a plausible batch code cannot participate in matching."""
    return bool(row.get("drug_name")) and plausible_batch(
        row.get("batch_norm") or row.get("batch_raw") or ""
    )
