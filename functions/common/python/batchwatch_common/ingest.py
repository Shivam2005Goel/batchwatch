"""The monthly loop: regulator PDF in, alerts on people's phones out.

Four stages, each independently callable so Step Functions can orchestrate
them and scripts/build_seed.py can run the same code on a laptop:

  fetch      list and download CDSCO alert PDFs
  extract    PDF -> raw table rows (pdfplumber, Textract for scans)
  normalise  raw rows -> canonical schema (Claude, with a heuristic fallback)
  fanout     newly flagged batches -> whose shelf is this on?

The fan-out stage is the one the whole project exists for.
"""
from __future__ import annotations

import io
import os
import re
from typing import Iterable

from . import bedrock
from .ids import row_hash
from .match import FLAGGED, UNCERTAIN, NSQIndex, match
from .normalise import canonical_row, row_is_usable
from .repo import (
    add_alert,
    alert_exists,
    bump_corpus_version,
    invalidate_index,
    save_nsq_rows,
    shelves_holding,
)
from .schema import classify_failure
from .store import get_store

MIN_ROWS_PER_PAGE = 3


# ------------------------------------------------------------------ extract


def extract_rows(pdf_bytes: bytes, use_textract: bool | None = None) -> list[list[str]]:
    """PDF -> list of raw table rows.

    Most CDSCO alerts carry a real text layer, so pdfplumber gets them for
    free. Some months are scans; those fall through to Textract, which costs
    money, so the fallback is measured per document rather than assumed.
    """
    rows: list[list[str]] = []
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        cells = [(c or "").strip() for c in row]
                        if any(cells):
                            rows.append(cells)
    except Exception as exc:  # noqa: BLE001 - a broken PDF must not kill the run
        print(f"pdfplumber failed: {type(exc).__name__}: {exc}")

    if use_textract is None:
        use_textract = os.environ.get("BW_TEXTRACT", "auto").lower() != "off"

    if len(rows) < MIN_ROWS_PER_PAGE and use_textract:
        textract_rows = extract_rows_textract(pdf_bytes)
        if len(textract_rows) > len(rows):
            return textract_rows
    return rows


def extract_rows_textract(pdf_bytes: bytes) -> list[list[str]]:
    """Textract TABLES fallback for scanned alerts."""
    try:
        import boto3

        client = boto3.client("textract")
        resp = client.analyze_document(
            Document={"Bytes": pdf_bytes}, FeatureTypes=["TABLES"]
        )
    except Exception as exc:  # noqa: BLE001
        print(f"textract unavailable: {type(exc).__name__}: {exc}")
        return []

    blocks = {b["Id"]: b for b in resp.get("Blocks", [])}
    rows: list[list[str]] = []

    def text_of(block: dict) -> str:
        words = []
        for rel in block.get("Relationships", []) or []:
            if rel["Type"] != "CHILD":
                continue
            for cid in rel["Ids"]:
                child = blocks.get(cid, {})
                if child.get("BlockType") == "WORD":
                    words.append(child.get("Text", ""))
                elif child.get("BlockType") == "SELECTION_ELEMENT":
                    if child.get("SelectionStatus") == "SELECTED":
                        words.append("X")
        return " ".join(words).strip()

    for block in resp.get("Blocks", []):
        if block.get("BlockType") != "TABLE":
            continue
        cells: dict[int, dict[int, str]] = {}
        for rel in block.get("Relationships", []) or []:
            if rel["Type"] != "CHILD":
                continue
            for cid in rel["Ids"]:
                cell = blocks.get(cid, {})
                if cell.get("BlockType") != "CELL":
                    continue
                cells.setdefault(cell["RowIndex"], {})[cell["ColumnIndex"]] = text_of(cell)
        for r in sorted(cells):
            row = [cells[r][c] for c in sorted(cells[r])]
            if any(row):
                rows.append(row)
    return rows


# ---------------------------------------------------------------- normalise

_HEADER_HINTS = {
    "drug_name": ("name of drug", "drug name", "product", "name of the drug", "drug"),
    "manufacturer": ("manufactured by", "manufacturer", "name and address", "mfd by", "firm"),
    "batch_raw": ("batch", "b.no", "batch no", "lot"),
    "mfg_date": ("mfg", "manufacturing", "date of mfg", "mfg date"),
    "exp_date": ("exp", "expiry", "date of expiry", "exp date"),
    "failure_reason": ("reason", "non-standard", "nature of", "defect", "reason for"),
    "lab": ("laboratory", "tested by", "lab", "drawn by"),
}


def _match_header(cell: str) -> str:
    text = (cell or "").strip().lower()
    if not text:
        return ""
    for field, hints in _HEADER_HINTS.items():
        for hint in hints:
            if hint in text:
                return field
    return ""


def find_header(rows: list[list[str]]) -> tuple[int, dict[int, str]]:
    """Locate the header row and its column mapping, or (-1, {})."""
    best_idx, best_map, best_score = -1, {}, 0
    for idx, row in enumerate(rows[:12]):
        mapping = {}
        for col, cell in enumerate(row):
            field = _match_header(cell)
            if field and field not in mapping.values():
                mapping[col] = field
        score = len(mapping)
        if score > best_score:
            best_idx, best_map, best_score = idx, mapping, score
    return (best_idx, best_map) if best_score >= 3 else (-1, {})


def normalise_heuristic(rows: list[list[str]], context: str = "") -> list[dict]:
    """Map raw rows without a model, using the header row.

    Used by build_seed when Bedrock is off, and as the fallback when a model
    call fails mid-run. Weaker than the LLM path on unusual layouts, which is
    exactly why the LLM path exists.
    """
    header_idx, mapping = find_header(rows)
    if header_idx < 0:
        return []

    out = []
    for row in rows[header_idx + 1 :]:
        record: dict[str, str] = {}
        for col, field in mapping.items():
            if col < len(row):
                record[field] = (row[col] or "").strip()
        if not record.get("batch_raw"):
            continue
        # Serial-number columns get mistaken for batch codes on some layouts.
        if re.fullmatch(r"\d{1,3}\.?", record.get("batch_raw", "")):
            continue
        record.setdefault("failure_reason", "")
        record["failure_class"] = classify_failure(record.get("failure_reason", ""))
        record["manufacturer_raw"] = record.pop("manufacturer", "")
        record["source_context"] = context
        out.append(record)
    return out


def normalise_rows(
    rows: list[list[str]], context: str = "", prefer_model: bool = True
) -> tuple[list[dict], str]:
    """Raw rows -> loose dicts, plus which path produced them."""
    if prefer_model and bedrock.available():
        mapped = bedrock.normalise_rows(rows, context=context)
        if mapped:
            return mapped, "bedrock"
    return normalise_heuristic(rows, context=context), "heuristic"


def to_canonical(
    mapped: Iterable[dict], alert_month: str = "", source_url: str = "", synthetic: bool = False
) -> list[dict]:
    """Loose dicts -> canonical NSQ rows, dropping anything unusable."""
    out = []
    for record in mapped:
        row = canonical_row(
            {
                **record,
                "alert_month": record.get("alert_month") or alert_month,
                "source_url": record.get("source_url") or source_url,
                "synthetic": synthetic,
            }
        )
        if row_is_usable(row):
            out.append(row)
    return out


# ------------------------------------------------------------------ fan-out


def fanout(rows: list[dict], deep: bool = False, notify: bool = True) -> dict:
    """Newly flagged batches -> alerts for the people holding them.

    The fast path is one GSI1 query per batch: "who has this skeleton on a
    shelf?". That is O(1) per flagged batch and is the access pattern the whole
    table design exists to serve.

    `deep` additionally re-scores every shelf item against the new rows, which
    catches shelf entries whose batch code was mis-read at scan time and so
    hashes to a different skeleton. It is O(shelf items) and is what the demo
    uses; at national scale this becomes a per-molecule sweep instead.
    """
    index = NSQIndex(rows)
    alerts_created: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        skeleton = row.get("batch_skeleton") or ""
        if not skeleton:
            continue
        for item in shelves_holding(skeleton):
            _maybe_alert(item, row, 1.0, FLAGGED, alerts_created, seen, notify)

    if deep:
        for item in _all_shelf_items():
            if not item.get("batch_norm"):
                continue
            result = match(
                {
                    "batch": item.get("batch_norm", ""),
                    "drug_name": item.get("drug_name", ""),
                    "manufacturer": item.get("manufacturer", ""),
                    "exp_date": item.get("exp_date", ""),
                },
                index,
            )
            if result.verdict in (FLAGGED, UNCERTAIN) and result.best:
                _maybe_alert(
                    item, result.best, result.score, result.verdict, alerts_created, seen, notify
                )

    return {
        "batches_checked": len(rows),
        "alerts_created": len(alerts_created),
        "alerts": alerts_created,
    }


def _all_shelf_items() -> list[dict]:
    return [i for i in get_store().scan_prefix("USER#") if i.get("type") == "ITEM"]


def _maybe_alert(
    item: dict,
    row: dict,
    score: float,
    verdict: str,
    created: list[dict],
    seen: set,
    notify: bool,
) -> None:
    user = (item.get("PK") or "").replace("USER#", "")
    item_id = item.get("item_id", "")
    h = row.get("row_hash") or row_hash(row)
    key = (user, item_id, h)
    if not user or key in seen:
        return
    seen.add(key)
    if alert_exists(user, item_id, h):
        return

    alert = add_alert(user, item, {**row, "row_hash": h}, score, verdict)
    created.append(alert)

    if notify:
        try:
            from .notify import send_alert_email

            send_alert_email(user, alert)
        except Exception as exc:  # noqa: BLE001 - delivery must not fail ingest
            print(f"notify failed for {user}: {type(exc).__name__}: {exc}")


# ------------------------------------------------------------------- save


def ingest_rows(rows: list[dict], deep: bool = True, notify: bool = True) -> dict:
    """Persist canonical rows, refresh the index, then fan out."""
    saved = save_nsq_rows(rows)
    invalidate_index()
    # Publish the new corpus generation so the read-path functions - which are
    # separate Lambdas holding their own warm index - rebuild on their next
    # request instead of answering from a stale corpus.
    version = bump_corpus_version()
    result = fanout(rows, deep=deep, notify=notify)
    result["rows_saved"] = saved
    result["corpus_version"] = version
    return result
