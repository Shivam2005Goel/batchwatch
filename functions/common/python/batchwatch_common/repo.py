"""Domain operations over the single table, so handlers stay thin.

Every function here is one or two store calls and no business logic beyond
key construction - the interesting logic lives in match.py and normalise.py.
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterable

from .ids import row_hash, sha256_hex, ulid
from .match import NSQIndex
from .normalise import batch_keys, canonical_row, is_expired
from .store import gsi_batch, gsi_drug, get_store, pk_batch, pk_user

NSQ_FIELDS = (
    "drug_name", "generic", "strength", "manufacturer_raw", "manufacturer",
    "batch_raw", "batch_norm", "batch_skeleton", "mfg_date", "exp_date",
    "failure_reason", "failure_class", "severity", "lab", "alert_month",
    "source_url", "synthetic",
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------ NSQ rows


def nsq_item(row: dict) -> dict:
    """Canonical NSQ row -> a table item."""
    row = canonical_row(row)
    h = row_hash(row)
    item = {
        "PK": pk_batch(row["batch_skeleton"]),
        "SK": f"NSQ#{row.get('alert_month') or '0000-00'}#{h}",
        "GSI1PK": gsi_drug(row.get("generic") or ""),
        "type": "NSQ",
        "row_hash": h,
        "ingested_at": now_iso(),
    }
    item.update({k: row.get(k) for k in NSQ_FIELDS})
    return item


def save_nsq_rows(rows: Iterable[dict]) -> int:
    store = get_store()
    return store.batch_put(nsq_item(r) for r in rows)


def nsq_for_skeleton(skeleton: str) -> list[dict]:
    return get_store().query(pk_batch(skeleton), "NSQ#")


def all_nsq_rows(limit: int | None = None) -> list[dict]:
    return get_store().scan_prefix("BATCH#", limit=limit)


# -------------------------------------------------------------- the index

_index: NSQIndex | None = None
_index_version = ""

INDEX_VERSION_SK = "INDEX_VERSION"


def corpus_version() -> str:
    """The corpus generation, shared across every Lambda via the table.

    The read path holds its index at module level, but the ingest that changes
    the corpus runs in a *different* function. Without a shared marker a warm
    read Lambda keeps answering from a stale index after an ingest - the alert
    lands in DynamoDB but the shelf still shows the item as clear, which is
    exactly the moment this project exists for.

    One eventually-consistent GetItem per request buys correctness here.
    """
    if os.environ.get("BW_INDEX_CHECK", "1") != "1":
        return os.environ.get("BW_INDEX_VERSION", "")
    try:
        item = get_store().get("SOURCE#CDSCO", INDEX_VERSION_SK) or {}
    except Exception as exc:  # noqa: BLE001 - never fail a read over a cache check
        print(f"corpus_version lookup failed: {type(exc).__name__}: {exc}")
        return _index_version
    return str(item.get("version") or os.environ.get("BW_INDEX_VERSION", ""))


def bump_corpus_version() -> str:
    """Tell every other Lambda that the corpus moved."""
    version = ulid()
    get_store().put(
        {
            "PK": "SOURCE#CDSCO",
            "SK": INDEX_VERSION_SK,
            "type": "INDEX_VERSION",
            "version": version,
            "updated_at": now_iso(),
        }
    )
    return version


def load_index(force: bool = False) -> NSQIndex:
    """Build (and then reuse) the in-memory NSQ index.

    Held at module level so warm Lambda invocations match in single-digit
    milliseconds with no database round trip, rebuilt when the shared corpus
    version says the corpus changed underneath us.
    """
    global _index, _index_version
    version = corpus_version()
    if _index is not None and not force and version == _index_version:
        return _index

    rows = _load_index_rows()
    index = NSQIndex(rows)
    index.version = version
    _index, _index_version = index, version
    return index


def _load_index_rows() -> list[dict]:
    """S3 JSONL if configured (one GET), otherwise straight from the table."""
    uri = os.environ.get("BW_INDEX_S3_URI", "")
    if uri.startswith("s3://"):
        import boto3

        bucket, _, key = uri[5:].partition("/")
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    return all_nsq_rows()


def invalidate_index() -> None:
    global _index
    _index = None


# ----------------------------------------------------------------- shelf


def shelf_item(user_sub: str, payload: dict, item_id: str | None = None) -> dict:
    batch_norm, skeleton = batch_keys(payload.get("batch") or payload.get("batch_raw") or "")
    item_id = item_id or ulid()
    return {
        "PK": pk_user(user_sub),
        "SK": f"ITEM#{item_id}",
        "GSI1PK": gsi_batch(skeleton),
        "type": "ITEM",
        "item_id": item_id,
        "drug_name": (payload.get("drug_name") or "").strip(),
        "manufacturer": (payload.get("manufacturer") or "").strip(),
        "batch_raw": (payload.get("batch") or payload.get("batch_raw") or "").strip(),
        "batch_norm": batch_norm,
        "batch_skeleton": skeleton,
        "mfg_date": payload.get("mfg_date") or "",
        "exp_date": payload.get("exp_date") or "",
        "nickname": (payload.get("nickname") or "").strip(),
        "added_at": now_iso(),
        "last_verdict": payload.get("verdict") or "NO_MATCH",
        "last_checked": now_iso(),
    }


def add_shelf_item(user_sub: str, payload: dict) -> dict:
    item = shelf_item(user_sub, payload)
    get_store().put(item)
    return item


def list_shelf(user_sub: str) -> list[dict]:
    items = get_store().query(pk_user(user_sub), "ITEM#")
    for item in items:
        item["expired"] = is_expired(item.get("exp_date") or "")
    return items


def get_shelf_item(user_sub: str, item_id: str) -> dict | None:
    return get_store().get(pk_user(user_sub), f"ITEM#{item_id}")


def delete_shelf_item(user_sub: str, item_id: str) -> bool:
    return get_store().delete(pk_user(user_sub), f"ITEM#{item_id}")


def update_shelf_verdict(item: dict, verdict: str) -> dict:
    item = dict(item)
    item["last_verdict"] = verdict
    item["last_checked"] = now_iso()
    get_store().put(item)
    return item


def shelves_holding(skeleton: str) -> list[dict]:
    """The reverse lookup. This single query is the entire product."""
    rows = get_store().query_gsi1(gsi_batch(skeleton))
    return [r for r in rows if r.get("type") == "ITEM"]


# ----------------------------------------------------------------- alerts


def add_alert(user_sub: str, item: dict, nsq_row: dict, score: float, verdict: str) -> dict:
    alert_id = ulid()
    alert = {
        "PK": pk_user(user_sub),
        "SK": f"ALERT#{now_iso()}#{alert_id}",
        "type": "ALERT",
        "alert_id": alert_id,
        "item_id": item.get("item_id", ""),
        "drug_name": item.get("drug_name") or nsq_row.get("drug_name", ""),
        "batch_raw": item.get("batch_raw", ""),
        "batch_norm": item.get("batch_norm", ""),
        "severity": nsq_row.get("severity", "LOW"),
        "failure_class": nsq_row.get("failure_class", "OTHER"),
        "failure_reason": nsq_row.get("failure_reason", ""),
        "alert_month": nsq_row.get("alert_month", ""),
        "source_url": nsq_row.get("source_url", ""),
        # Identity of the NSQ row, so re-ingesting a month cannot alert the
        # same person about the same batch twice.
        "row_hash": nsq_row.get("row_hash") or row_hash(nsq_row),
        "manufacturer": nsq_row.get("manufacturer_raw", ""),
        "score": round(float(score), 4),
        "verdict": verdict,
        "created_at": now_iso(),
        "read": False,
        "notified": False,
    }
    get_store().put(alert)
    return alert


def list_alerts(user_sub: str, limit: int = 50) -> list[dict]:
    return get_store().query(pk_user(user_sub), "ALERT#", limit=limit, descending=True)


def alert_exists(user_sub: str, item_id: str, row_h: str) -> bool:
    """Ingesting the same month twice must not alert the same person twice."""
    for alert in get_store().query(pk_user(user_sub), "ALERT#"):
        if alert.get("item_id") == item_id and alert.get("row_hash") == row_h:
            return True
    return False


# ------------------------------------------------------------- ingest docs


def doc_key(url: str) -> str:
    return f"DOC#{sha256_hex(url, 20)}"


def doc_seen(url: str) -> bool:
    return get_store().get("SOURCE#CDSCO", doc_key(url)) is not None


def mark_doc(url: str, **fields) -> dict:
    item = {
        "PK": "SOURCE#CDSCO",
        "SK": doc_key(url),
        "type": "DOC",
        "url": url,
        "seen_at": now_iso(),
    }
    item.update(fields)
    get_store().put(item)
    return item


def list_docs(limit: int = 200) -> list[dict]:
    return get_store().query("SOURCE#CDSCO", "DOC#", limit=limit)


# ----------------------------------------------------------- pharmacy jobs


def put_job(job: dict) -> dict:
    item = {
        "PK": f"JOB#{job['job_id']}",
        "SK": "META",
        "type": "JOB",
        "ttl": int(time.time()) + 24 * 3600,
    }
    item.update(job)
    get_store().put(item)
    return item


def get_job(job_id: str) -> dict | None:
    return get_store().get(f"JOB#{job_id}", "META")


# ------------------------------------------------------------------ stats


def corpus_stats(index: NSQIndex | None = None) -> dict:
    index = index or load_index()
    months = sorted({r.get("alert_month") or "" for r in index.rows if r.get("alert_month")})
    synthetic = sum(1 for r in index.rows if r.get("synthetic"))
    severities: dict[str, int] = {}
    for row in index.rows:
        sev = row.get("severity") or "LOW"
        severities[sev] = severities.get(sev, 0) + 1
    return {
        "rows": len(index.rows),
        "distinct_batches": len(index.by_skeleton),
        "distinct_molecules": len(index.by_generic),
        "alert_months": len(months),
        "earliest_alert_month": months[0] if months else "",
        "latest_alert_month": months[-1] if months else "",
        "severities": severities,
        "synthetic_rows": synthetic,
        "corpus_is_synthetic": synthetic > 0 and synthetic == len(index.rows),
        "index_version": index.version,
    }
