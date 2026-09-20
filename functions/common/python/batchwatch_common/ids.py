"""Sortable identifiers and stable hashes.

ULIDs matter here because shelf items and alerts are read with a
begins_with/descending sort-key query: an id whose lexical order matches its
creation order means "my newest alerts" is one query with no sorting.
"""
from __future__ import annotations

import hashlib
import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def ulid(now_ms: int | None = None) -> str:
    """26-character Crockford base32 ULID: 48-bit time + 80 bits of entropy."""
    ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return _encode(ms, 10) + _encode(int.from_bytes(os.urandom(10), "big"), 16)


def sha256_hex(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def row_hash(row: dict) -> str:
    """Stable identity for an NSQ row, so re-ingesting a PDF is idempotent."""
    parts = "|".join(
        str(row.get(k, "")).strip().lower()
        for k in ("batch_norm", "drug_name", "manufacturer", "alert_month", "failure_reason")
    )
    return sha256_hex(parts, 16)
