"""Ingest stage 4: whose shelf is this on?

This is the function the project exists for. Everything upstream is plumbing
to get a clean batch skeleton into this query; everything downstream is a
notification.
"""
from __future__ import annotations

import os

from batchwatch_common.blob import get_blob
from batchwatch_common.ingest import ingest_rows
from batchwatch_common.repo import mark_doc


def lambda_handler(event: dict, context=None) -> dict:
    refs = event.get("canonical_refs")
    if not refs:
        single = event.get("canonical_ref")
        refs = [single] if single else []

    rows: list[dict] = []
    for ref in refs:
        rows.extend(get_blob(ref))

    if event.get("rows"):
        rows.extend(event["rows"])

    if not rows:
        return {"rows_saved": 0, "alerts_created": 0, "alerts": [], "batches_checked": 0}

    result = ingest_rows(
        rows,
        deep=bool(event.get("deep", True)),
        notify=bool(event.get("notify", os.environ.get("BW_SES_FROM"))),
    )

    for url in event.get("urls") or []:
        mark_doc(url, status="INGESTED", alerts_created=result["alerts_created"])

    # The index is held at module level across warm invocations, so the read
    # path needs to be told the corpus moved.
    result["index_version_hint"] = (
        "bump BW_INDEX_VERSION on the read-path functions to force a rebuild"
    )
    return result
