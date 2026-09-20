"""Ingest stage 2: one PDF -> raw table rows.

Runs once per document inside a Step Functions Map state. Rows go to S3 rather
than into the state payload, which is capped at 256KB.
"""
from __future__ import annotations

from batchwatch_common.blob import get_pdf, put_blob
from batchwatch_common.ids import sha256_hex
from batchwatch_common.ingest import extract_rows
from batchwatch_common.repo import mark_doc


def lambda_handler(event: dict, context=None) -> dict:
    run_id = event["run_id"]
    url = event.get("url", "")
    pdf_ref = event["pdf_ref"]

    data = get_pdf(pdf_ref)
    rows = extract_rows(data)
    name = f"rows-{sha256_hex(url or pdf_ref, 12)}"
    rows_ref = put_blob(run_id, name, rows)

    if url:
        mark_doc(url, status="EXTRACTED", rows=len(rows), rows_ref=rows_ref)

    return {
        "run_id": run_id,
        "url": url,
        "alert_month": event.get("alert_month", ""),
        "rows_ref": rows_ref,
        "row_count": len(rows),
    }
