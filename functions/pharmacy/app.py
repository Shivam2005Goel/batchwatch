"""Bulk stock check for a chemist.

One person checking their shelf protects everyone who would have bought from
it, which is where the impact argument lives. The work is done synchronously -
matching is sub-millisecond per row against the in-memory index, so a thousand
line stock list finishes inside one invocation - but the result is stored under
a job id so the client can poll or share it.
"""
from __future__ import annotations

import csv
import io

from batchwatch_common.http import (
    HttpError,
    handler,
    method_of,
    ok,
    parse_body,
    path_params,
    response,
    user_sub,
)
from batchwatch_common.ids import ulid
from batchwatch_common.match import FLAGGED, NO_MATCH, UNCERTAIN
from batchwatch_common.normalise import plausible_batch
from batchwatch_common.repo import get_job, load_index, now_iso, put_job
from batchwatch_common.schema import SEVERITY_ORDER
from batchwatch_common.verdict import DISCLAIMER, build_verdict

MAX_ROWS = 2000

# Header spellings a pharmacy's export might plausibly use.
_FIELD_ALIASES = {
    "drug_name": {"drug", "drug_name", "product", "item", "medicine", "name", "description"},
    "batch": {"batch", "batch_no", "batchno", "batch number", "b.no", "bno", "lot", "lot_no"},
    "manufacturer": {"manufacturer", "mfr", "company", "make", "maker", "mfg_by", "supplier"},
    "exp_date": {"exp", "expiry", "exp_date", "expiry_date", "expires", "exp date"},
    "quantity": {"qty", "quantity", "stock", "count", "units", "packs"},
}


@handler
def lambda_handler(event: dict, context=None) -> dict:
    method = method_of(event)
    if method == "GET":
        return _get_results(event)
    if method != "POST":
        raise HttpError(405, f"{method} not allowed")
    return _run_check(event)


# ------------------------------------------------------------------ parsing


def _canonical_header(name: str) -> str:
    key = (name or "").strip().lower().replace(".", "").replace("-", "_")
    for field, aliases in _FIELD_ALIASES.items():
        if key in aliases or key.replace("_", " ") in aliases:
            return field
    return ""


def parse_stock(body: dict) -> list[dict]:
    """Accept a CSV blob, pasted lines, or a JSON array."""
    if isinstance(body.get("items"), list):
        return [dict(item) for item in body["items"][:MAX_ROWS]]

    text = (body.get("csv") or body.get("text") or "").strip()
    if not text:
        raise HttpError(400, "send 'csv' (or 'text'), or an 'items' array")

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    dialect_sample = "\n".join(lines[:5])
    delimiter = "\t" if "\t" in dialect_sample else ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return []

    header_map = {i: _canonical_header(cell) for i, cell in enumerate(rows[0])}
    has_header = sum(1 for v in header_map.values() if v) >= 2
    body_rows = rows[1:] if has_header else rows

    out: list[dict] = []
    for row in body_rows[:MAX_ROWS]:
        if has_header:
            item = {}
            for i, cell in enumerate(row):
                field = header_map.get(i)
                if field:
                    item[field] = cell.strip()
        else:
            # Positional fallback: drug, batch, manufacturer, expiry, qty.
            keys = ["drug_name", "batch", "manufacturer", "exp_date", "quantity"]
            item = {keys[i]: cell.strip() for i, cell in enumerate(row) if i < len(keys)}
        if any(item.values()):
            out.append(item)
    return out


# ------------------------------------------------------------------ running


def _run_check(event: dict) -> dict:
    sub = user_sub(event)
    body = parse_body(event)
    stock = parse_stock(body)
    if not stock:
        raise HttpError(400, "no usable rows found in the stock list")

    index = load_index()
    results: list[dict] = []
    counts = {FLAGGED: 0, UNCERTAIN: 0, NO_MATCH: 0, "SKIPPED": 0}

    for line_no, item in enumerate(stock, start=1):
        batch = (item.get("batch") or "").strip()
        drug = (item.get("drug_name") or "").strip()

        if not batch or not plausible_batch(batch):
            counts["SKIPPED"] += 1
            results.append(
                {
                    "line": line_no,
                    "input": item,
                    "verdict": "SKIPPED",
                    "tone": "grey",
                    "reason": "No usable batch number on this line.",
                }
            )
            continue

        verdict = build_verdict(
            {
                "batch": batch,
                "drug_name": drug,
                "manufacturer": item.get("manufacturer") or "",
                "exp_date": item.get("exp_date") or "",
            },
            index,
            allow_adjudication=False,
        )
        counts[verdict["verdict"]] += 1
        results.append(
            {
                "line": line_no,
                "input": item,
                "verdict": verdict["verdict"],
                "tone": verdict["tone"],
                "severity": verdict["severity"],
                "score": verdict["score"],
                "reason": verdict["reason"],
                "match": verdict["match"],
                "expired": verdict["expired"],
            }
        )

    results.sort(
        key=lambda r: (
            {FLAGGED: 0, UNCERTAIN: 1, NO_MATCH: 2, "SKIPPED": 3}[r["verdict"]],
            SEVERITY_ORDER.get(r.get("severity") or "", 9),
            r["line"],
        )
    )

    job = {
        "job_id": ulid(),
        "owner": sub,
        "created_at": now_iso(),
        "rows": len(stock),
        "counts": counts,
        "results": results,
        "corpus_rows": len(index),
        "disclaimer": DISCLAIMER,
    }
    put_job(job)
    return response(201, _public(job))


def _get_results(event: dict) -> dict:
    sub = user_sub(event)
    job_id = (path_params(event).get("id") or "").strip()
    if not job_id:
        raise HttpError(400, "job id is required")
    job = get_job(job_id)
    if not job:
        raise HttpError(404, "no such job (results are kept for 24 hours)")
    if job.get("owner") and job["owner"] != sub:
        raise HttpError(403, "this job belongs to someone else")
    return ok(_public(job))


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("PK", "SK", "type", "ttl", "owner")}
