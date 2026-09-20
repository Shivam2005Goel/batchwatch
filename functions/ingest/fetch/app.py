"""Ingest stage 1: find and download new CDSCO alert PDFs.

Idempotent by URL hash - a document already recorded in SOURCE#CDSCO is
skipped, so the monthly schedule can run as often as it likes.
"""
from __future__ import annotations

from batchwatch_common.blob import put_pdf
from batchwatch_common.cdsco import discover, fetch
from batchwatch_common.ids import sha256_hex, ulid
from batchwatch_common.repo import doc_seen, mark_doc


def lambda_handler(event: dict, context=None) -> dict:
    run_id = event.get("run_id") or ulid()
    limit = int(event.get("limit") or 6)
    force = bool(event.get("force"))

    # An explicit list lets the demo replay a held-back month without touching
    # the network.
    links = event.get("documents") or discover()

    documents = []
    skipped = 0
    for link in links:
        url = link["url"] if isinstance(link, dict) else str(link)
        if not force and doc_seen(url):
            skipped += 1
            continue
        try:
            data = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"download failed {url}: {type(exc).__name__}: {exc}")
            mark_doc(url, status="FETCH_FAILED", error=f"{type(exc).__name__}: {exc}")
            continue

        name = f"{sha256_hex(url, 16)}.pdf"
        ref = put_pdf(run_id, name, data)
        mark_doc(
            url,
            status="FETCHED",
            pdf_ref=ref,
            bytes=len(data),
            alert_month=(link.get("alert_month") if isinstance(link, dict) else "") or "",
        )
        documents.append(
            {
                "url": url,
                "pdf_ref": ref,
                "alert_month": (link.get("alert_month") if isinstance(link, dict) else "") or "",
                "bytes": len(data),
            }
        )
        if len(documents) >= limit:
            break

    return {
        "run_id": run_id,
        "documents": documents,
        "fetched": len(documents),
        "skipped_already_seen": skipped,
    }
