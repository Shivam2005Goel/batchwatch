"""Pull label fields out of a block of text, with no model in the loop.

This is the path behind "type it in instead", and the fallback when Bedrock is
unavailable or declines. It is deliberately conservative: it would rather
return an empty batch field than a confident wrong one, because a wrong batch
code produces a wrong verdict about someone's medicine.
"""
from __future__ import annotations

import re

from .normalise import (
    STRENGTH_RE,
    is_expired,
    norm_batch,
    parse_month,
    plausible_batch,
)

_BATCH_LABEL_RE = re.compile(
    r"(?:B\.?\s*NO\.?|BATCH\s*(?:NO\.?|NUMBER)?|BN|B/N|LOT\s*(?:NO\.?)?|L\.?\s*NO\.?)"
    r"[ \t]*[:.\-]?[ \t]*([A-Z0-9][A-Z0-9 \t\-/]{2,24})",
    re.IGNORECASE,
)

_MFG_LABEL_RE = re.compile(
    r"(?:MFG|MFD|MANUFACTURED|DATE\s*OF\s*MFG)"
    r"\s*\.?\s*(?:DT\.?|DATE)?\s*[:.\-]?\s*([A-Z0-9/.\- ]{4,12})",
    re.IGNORECASE,
)

_EXP_LABEL_RE = re.compile(
    r"(?:EXP|EXPY|EXPIRY|EXPIRES?|USE\s*BEFORE|BEST\s*BEFORE)"
    r"\s*\.?\s*(?:DT\.?|DATE)?\s*[:.\-]?\s*([A-Z0-9/.\- ]{4,12})",
    re.IGNORECASE,
)

_MAKER_LABEL_RE = re.compile(
    r"(?:MFD\.?\s*BY|MANUFACTURED\s*BY|MKTD\.?\s*BY|MARKETED\s*BY|MFG\.?\s*BY)"
    r"\s*[:.\-]?\s*(.+)",
    re.IGNORECASE,
)

_MAKER_HINT_RE = re.compile(
    r"\b(?:PHARMA\w*|LABORAT\w*|LABS?|HEALTHCARE|BIOTECH|REMEDIES|FORMULATIONS|"
    r"DRUGS|LIFE\s*SCIENCES|MEDICARE|BIOCEUTICALS)\b",
    re.IGNORECASE,
)

_NOISE_LINE_RE = re.compile(
    r"^\s*(?:MRP|M\.R\.P|RS\.?|₹|PRICE|INCL|KEEP|STORE|SCHEDULE|CAUTION|"
    r"WARNING|DOSAGE|FOR\s+THE\s+USE|NOT\s+FOR|TO\s+BE\s+SOLD)\b",
    re.IGNORECASE,
)

# Label words that mark where the batch code ends when the printer ran several
# fields onto one line ("B.No. KP4021H MFG 03/2026").
_NEXT_FIELD_RE = re.compile(
    r"\b(?:MFG|MFD|EXP|EXPY|EXPIRY|EXPIRES|MRP|RS|PRICE|DATE|USE|BEST|MKTD)\b",
    re.IGNORECASE,
)

# Things that look like a batch code but are not.
_NOT_A_BATCH = re.compile(
    r"^(?:\d{1,2}[/.-]\d{2,4}|\d{5,6}|IP|BP|USP|MRP|GST|ISO|HSN)$", re.IGNORECASE
)


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in (text or "").replace("\r", "\n").split("\n"):
        line = " ".join(raw.split())
        if line:
            lines.append(line)
    return lines


def _first_group(pattern: re.Pattern, text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _trim_batch(value: str) -> str:
    """Cut a captured run down to the batch code itself.

    Foil printing separates the code with spaces or dashes as often as not, so
    rather than assuming a single token, cut at the next field label, then try
    the longest remaining run and shorten until something plausible is left.
    """
    value = _NEXT_FIELD_RE.split(value, maxsplit=1)[0].strip(" \t.:-")
    tokens = value.split()
    for take in range(len(tokens), 0, -1):
        candidate = "".join(tokens[:take])
        if plausible_batch(candidate):
            return norm_batch(candidate)
    return ""


def find_batch(text: str) -> str:
    """The labelled batch code, or the best unlabelled candidate."""
    labelled = _first_group(_BATCH_LABEL_RE, text)
    if labelled:
        trimmed = _trim_batch(labelled)
        if trimmed:
            return trimmed

    # No label: look for a token shaped like a batch code, skipping dates,
    # strengths and prices.
    best = ""
    for line in _clean_lines(text):
        if _NOISE_LINE_RE.search(line):
            continue
        stripped = STRENGTH_RE.sub(" ", line)
        for token in re.split(r"[\s,;()]+", stripped):
            token = token.strip(".:-")
            if not token or _NOT_A_BATCH.match(token) or _NEXT_FIELD_RE.fullmatch(token):
                continue
            if parse_month(token):
                continue
            norm = norm_batch(token)
            if not plausible_batch(norm):
                continue
            # Prefer mixed alphanumeric codes; a bare run of digits is far more
            # likely to be a price, a pack size or a licence number.
            if any(c.isalpha() for c in norm) and (not best or len(norm) > len(best)):
                best = norm
    return best


def find_dates(text: str) -> tuple[str, str]:
    """(mfg_date, exp_date) as YYYY-MM, using labels where present."""
    mfg = parse_month(_first_group(_MFG_LABEL_RE, text))
    exp = parse_month(_first_group(_EXP_LABEL_RE, text))
    if mfg and exp:
        return (exp, mfg) if mfg > exp else (mfg, exp)

    # Unlabelled dates: two on a strip are conventionally MFG then EXP. A
    # single unlabelled date is never assumed to fill the missing field -
    # guessing an expiry wrong is worse than leaving it blank.
    found: list[str] = []
    for line in _clean_lines(text):
        for token in re.split(r"[\s,;()]+", line):
            month = parse_month(token)
            if month and month not in found:
                found.append(month)
    found.sort()

    if len(found) >= 2:
        if not mfg and not exp:
            mfg, exp = found[0], found[-1]
        elif not exp:
            exp = found[-1]
        elif not mfg:
            mfg = found[0]

    if mfg and exp and mfg > exp:
        mfg, exp = exp, mfg
    return mfg, exp


def find_manufacturer(text: str) -> str:
    labelled = _first_group(_MAKER_LABEL_RE, text)
    if labelled:
        return labelled.strip(" .,:-")
    for line in _clean_lines(text):
        if _MAKER_HINT_RE.search(line) and not STRENGTH_RE.search(line):
            return line.strip(" .,:-")
    return ""


def find_drug_name(text: str) -> str:
    """The product line: normally the one carrying the strength."""
    lines = _clean_lines(text)
    for line in lines:
        if _NOISE_LINE_RE.search(line) or _MAKER_HINT_RE.search(line):
            continue
        if STRENGTH_RE.search(line) and len(line) > 4:
            return line.strip(" .,:-")
    for line in lines:
        if _NOISE_LINE_RE.search(line) or _MAKER_HINT_RE.search(line):
            continue
        if len(line) > 6 and not _BATCH_LABEL_RE.search(line):
            return line.strip(" .,:-")
    return ""


def parse_label(text: str) -> dict:
    """Best-effort structured read of a medicine label.

    Returns the same shape as the Bedrock vision extractor so that both paths
    feed the matcher identically.
    """
    text = text or ""
    batch = find_batch(text)
    mfg, exp = find_dates(text)
    drug = find_drug_name(text)
    manufacturer = find_manufacturer(text)

    present = sum(bool(x) for x in (batch, drug, manufacturer, exp))
    confidence = round(min(0.85, 0.25 + 0.15 * present), 2) if batch else 0.2

    return {
        "drug_name": drug,
        "manufacturer": manufacturer,
        "batch": batch,
        "mfg_date": mfg,
        "exp_date": exp,
        "confidence": confidence,
        "legible": bool(batch and drug),
        "expired": is_expired(exp),
        "source": "text-parser",
        "notes": "" if batch else "No batch number found in the text provided.",
        "raw_text": text.strip()[:2000],
    }
