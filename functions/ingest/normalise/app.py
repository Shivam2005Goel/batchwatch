"""Ingest stage 3: raw table rows -> the canonical schema.

This is the single best use of a model in the project. CDSCO column headings
and column order change between months and between state regulators, so a
parser per layout is a losing game; handing each row to Claude with a strict
output schema is not.
"""
from __future__ import annotations

from batchwatch_common.blob import get_blob, put_blob
from batchwatch_common.ingest import normalise_rows, to_canonical
from batchwatch_common.repo import mark_doc

# Rows are sent to the model in batches so one bad page cannot cost a whole
# document, and so a long alert stays inside the output token budget.
BATCH_SIZE = 40


def lambda_handler(event: dict, context=None) -> dict:
    run_id = event["run_id"]
    url = event.get("url", "")
    alert_month = event.get("alert_month", "")
    rows = get_blob(event["rows_ref"])

    context_note = f"CDSCO drug alert, {alert_month or 'month unknown'}, source {url}"
    mapped: list[dict] = []
    paths: set[str] = set()

    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        chunk_mapped, path = normalise_rows(chunk, context=context_note)
        mapped.extend(chunk_mapped)
        paths.add(path)

    canonical = to_canonical(mapped, alert_month=alert_month, source_url=url)
    canonical_ref = put_blob(run_id, f"canonical-{abs(hash(url or run_id)) % 10**10}", canonical)

    if url:
        mark_doc(
            url,
            status="NORMALISED",
            canonical_rows=len(canonical),
            canonical_ref=canonical_ref,
            normaliser="+".join(sorted(paths)),
        )

    return {
        "run_id": run_id,
        "url": url,
        "alert_month": alert_month,
        "canonical_ref": canonical_ref,
        "canonical_count": len(canonical),
        "normaliser": "+".join(sorted(paths)),
    }
