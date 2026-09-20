"""GET /search and GET /stats - the public, no-login surface.

/search returns evidence, not a verdict. A bare batch code is not enough to
tell someone their medicine was recalled (codes are short and collide across
manufacturers), so this endpoint lists what the regulator published and lets
the reader compare the manufacturer themselves.
"""
from __future__ import annotations

from batchwatch_common import bedrock
from batchwatch_common.fuzz import token_set_ratio
from batchwatch_common.http import HttpError, handler, method_of, ok, query_params
from batchwatch_common.normalise import batch_keys, norm_generic, norm_manufacturer
from batchwatch_common.repo import corpus_stats, load_index
from batchwatch_common.verdict import DISCLAIMER

MAX_RESULTS = 50


def _looks_like_batch(q: str) -> bool:
    norm, _ = batch_keys(q)
    return len(norm) >= 3 and any(c.isdigit() for c in norm)


@handler
def lambda_handler(event: dict, context=None) -> dict:
    path = (
        (event.get("requestContext") or {}).get("http", {}).get("path")
        or event.get("rawPath")
        or event.get("path")
        or "/"
    )
    if path.rstrip("/").endswith("/stats"):
        return _stats()
    if method_of(event) != "GET":
        raise HttpError(405, "only GET is allowed here")
    return _search(event)


def _stats() -> dict:
    index = load_index()
    stats = corpus_stats(index)
    stats["bedrock"] = bedrock.status()
    stats["disclaimer"] = DISCLAIMER
    return ok(stats)


def _search(event: dict) -> dict:
    params = query_params(event)
    q = (params.get("q") or "").strip()
    limit = min(int(params.get("limit") or 20), MAX_RESULTS)
    if len(q) < 3:
        raise HttpError(400, "q must be at least 3 characters")

    index = load_index()

    if _looks_like_batch(q):
        scored = index.search({"batch": q}, limit=limit)
        rows = [
            {**s.row, "_score": round(s.score, 4), "_matched_on": "batch"}
            for s in scored
            if s.score >= 0.6
        ]
        mode = "batch"
    else:
        rows = _text_search(index, q, limit)
        mode = "text"

    return ok(
        {
            "query": q,
            "mode": mode,
            "count": len(rows),
            "results": rows[:limit],
            "note": (
                "These are published regulator alerts matching your search. "
                "Check the manufacturer and expiry against your strip before "
                "concluding anything - batch codes repeat across companies."
            ),
            "disclaimer": DISCLAIMER,
        }
    )


def _text_search(index, q: str, limit: int) -> list[dict]:
    """Drug or manufacturer search across the corpus."""
    generic_q = norm_generic(q)
    mfr_q = norm_manufacturer(q)
    scored: list[tuple[float, dict]] = []

    for row in index.rows:
        best = 0.0
        matched = ""
        if generic_q:
            s = token_set_ratio(generic_q, row.get("generic") or "") / 100.0
            if s > best:
                best, matched = s, "drug"
        if mfr_q:
            s = token_set_ratio(mfr_q, row.get("manufacturer") or "") / 100.0
            if s > best:
                best, matched = s, "manufacturer"
        if best >= 0.75:
            scored.append((best, {**row, "_score": round(best, 4), "_matched_on": matched}))

    scored.sort(key=lambda pair: (-pair[0], pair[1].get("alert_month", "")))
    return [row for _, row in scored[: limit * 2]]
