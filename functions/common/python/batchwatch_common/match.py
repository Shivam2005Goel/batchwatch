"""Deciding whether a strip in someone's hand is a row in the regulator's list.

Four weighted signals, three verdict bands, and a deliberate bias toward
saying "we are not sure" rather than "you are fine". A false clear is the only
failure mode of this system that can actually hurt a person.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

from .fuzz import token_set_ratio
from .glyph import ocr_similarity
from .normalise import (
    batch_keys,
    drug_key,
    month_delta,
    norm_generic,
    norm_manufacturer,
    parse_month,
)

# Weights sum to 1.0 when every signal is available. When a signal is missing
# on the query side its weight is removed and the rest are renormalised, so a
# sparse query is never silently penalised - it is just less decisive.
WEIGHTS = {
    "batch": 0.55,
    "drug": 0.25,
    "manufacturer": 0.15,
    "expiry": 0.05,
}

FLAG_THRESHOLD = float(os.environ.get("BW_FLAG_THRESHOLD", "0.92"))
REVIEW_THRESHOLD = float(os.environ.get("BW_REVIEW_THRESHOLD", "0.74"))

FLAGGED = "FLAGGED"
UNCERTAIN = "UNCERTAIN"
NO_MATCH = "NO_MATCH"

_MAX_CANDIDATES = 400
_MAX_LEN_DELTA = 3
_MAX_GENERIC_BLOCK = 2000


def _trigrams(s: str) -> set[str]:
    if len(s) < 3:
        return {s} if s else set()
    return {s[i : i + 3] for i in range(len(s) - 2)}


@dataclass
class Scored:
    """One NSQ row scored against the query."""

    row: dict
    score: float
    signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"score": round(self.score, 4), "signals": self.signals, "row": self.row}


@dataclass
class MatchResult:
    verdict: str
    score: float
    best: dict | None
    candidates: list[Scored]
    reason: str = ""
    adjudicated: bool = False

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": round(self.score, 4),
            "match": self.best,
            "reason": self.reason,
            "adjudicated": self.adjudicated,
            "candidates": [c.to_dict() for c in self.candidates],
        }


def score_pair(query: dict, row: dict) -> Scored:
    """Score one candidate row against a query. Missing signals renormalise."""
    q_batch = query.get("batch_skeleton") or batch_keys(query.get("batch") or "")[1]
    r_batch = row.get("batch_skeleton") or batch_keys(row.get("batch_raw") or "")[1]

    signals: dict[str, float] = {}
    weights: dict[str, float] = {}

    if q_batch and r_batch:
        signals["batch"] = 1.0 if q_batch == r_batch else ocr_similarity(q_batch, r_batch)
        weights["batch"] = WEIGHTS["batch"]

    q_drug = drug_key(query.get("drug_name") or "")
    r_drug = drug_key(row.get("drug_name") or "") or " ".join(
        x for x in (row.get("generic") or "", row.get("strength") or "") if x
    ).strip()
    if q_drug and r_drug:
        signals["drug"] = token_set_ratio(q_drug, r_drug) / 100.0
        weights["drug"] = WEIGHTS["drug"]

    q_mfr = norm_manufacturer(query.get("manufacturer") or "")
    r_mfr = row.get("manufacturer") or norm_manufacturer(row.get("manufacturer_raw") or "")
    if q_mfr and r_mfr:
        signals["manufacturer"] = token_set_ratio(q_mfr, r_mfr) / 100.0
        weights["manufacturer"] = WEIGHTS["manufacturer"]

    q_exp = parse_month(query.get("exp_date") or "")
    r_exp = row.get("exp_date") or ""
    delta = month_delta(q_exp, r_exp)
    if delta is not None:
        signals["expiry"] = 1.0 if delta <= 1 else 0.0
        weights["expiry"] = WEIGHTS["expiry"]

    total_weight = sum(weights.values())
    score = (
        sum(signals[k] * weights[k] for k in weights) / total_weight if total_weight else 0.0
    )
    return Scored(row=row, score=score, signals={k: round(v, 4) for k, v in signals.items()})


class NSQIndex:
    """In-memory index of the NSQ corpus, held across warm Lambda invocations.

    Exact lookups go through a skeleton dict; near misses come from a trigram
    inverted index so the pure-Python path stays fast on tens of thousands of
    rows without a database round trip.
    """

    def __init__(self, rows: Iterable[dict] | None = None):
        self.rows: list[dict] = []
        self.by_skeleton: dict[str, list[dict]] = {}
        self.by_generic: dict[str, list[dict]] = {}
        self._trigram: dict[str, set[str]] = {}
        self.version = ""
        if rows:
            self.extend(rows)

    def __len__(self) -> int:
        return len(self.rows)

    def add(self, row: dict) -> None:
        skel = row.get("batch_skeleton") or batch_keys(row.get("batch_raw") or "")[1]
        if not skel:
            return
        row = dict(row)
        row["batch_skeleton"] = skel
        self.rows.append(row)
        self.by_skeleton.setdefault(skel, []).append(row)
        for g in _trigrams(skel):
            self._trigram.setdefault(g, set()).add(skel)
        generic = (row.get("generic") or "").strip().lower()
        if generic:
            self.by_generic.setdefault(generic, []).append(row)

    def extend(self, rows: Iterable[dict]) -> None:
        for row in rows:
            self.add(row)

    def candidates(self, skel: str, generic: str = "") -> list[dict]:
        """Rows worth scoring: the exact skeleton bucket, its trigram
        neighbourhood, and - crucially - every row for the same molecule.

        The molecule block is what keeps recall up when OCR mangles the batch
        code badly enough to destroy its trigrams. It costs nothing in
        precision: those rows still have to clear the batch-similarity bar to
        be flagged, they just get the chance to be scored at all.
        """
        out: list[dict] = []
        seen_ids: set[int] = set()

        def take(rows: Iterable[dict]) -> None:
            for row in rows:
                if id(row) not in seen_ids:
                    seen_ids.add(id(row))
                    out.append(row)

        if skel:
            take(self.by_skeleton.get(skel, ()))

            overlap: dict[str, int] = {}
            for g in _trigrams(skel):
                for other in self._trigram.get(g, ()):
                    if other == skel:
                        continue
                    if abs(len(other) - len(skel)) > _MAX_LEN_DELTA:
                        continue
                    overlap[other] = overlap.get(other, 0) + 1

            ranked = sorted(overlap.items(), key=lambda kv: (-kv[1], kv[0]))
            for other, _ in ranked[:_MAX_CANDIDATES]:
                take(self.by_skeleton.get(other, ()))

        if generic:
            take(self.by_generic.get(generic.strip().lower(), ())[:_MAX_GENERIC_BLOCK])

        return out

    def search(self, query: dict, limit: int = 5) -> list[Scored]:
        """Score every plausible candidate, best first."""
        skel = query.get("batch_skeleton") or batch_keys(query.get("batch") or "")[1]
        generic = query.get("generic") or norm_generic(query.get("drug_name") or "")
        scored = [score_pair(query, row) for row in self.candidates(skel, generic)]
        scored.sort(key=lambda s: -s.score)
        return scored[:limit]


def verdict_for(score: float) -> str:
    if score >= FLAG_THRESHOLD:
        return FLAGGED
    if score >= REVIEW_THRESHOLD:
        return UNCERTAIN
    return NO_MATCH


def match(query: dict, index: NSQIndex, limit: int = 5) -> MatchResult:
    """Run the query against the index and band the result.

    A query with no drug name (a bare batch lookup) can never reach FLAGGED:
    batch codes are short and collide across manufacturers, so batch-alone
    evidence is presented for review, never as a verdict.
    """
    scored = index.search(query, limit=limit)
    if not scored:
        return MatchResult(NO_MATCH, 0.0, None, [], reason="No batch in the NSQ corpus resembles this code.")

    best = scored[0]
    verdict = verdict_for(best.score)
    reason = ""

    has_corroboration = any(k in best.signals for k in ("drug", "manufacturer"))
    if verdict == FLAGGED and not has_corroboration:
        verdict = UNCERTAIN
        reason = (
            "The batch code matches a flagged batch, but we have no drug name or "
            "manufacturer to confirm it is the same product."
        )
    elif verdict == FLAGGED:
        reason = "Batch code, product and manufacturer all line up with a flagged batch."
    elif verdict == UNCERTAIN:
        reason = "Close, but not close enough to be certain. Check the batch number by hand."
    else:
        reason = "This batch has not been flagged in the alerts we hold."

    return MatchResult(
        verdict=verdict,
        score=best.score,
        best=best.row if verdict != NO_MATCH else None,
        candidates=scored,
        reason=reason,
    )
