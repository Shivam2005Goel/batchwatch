"""The single-table persistence layer, behind one small interface.

Two drivers implement it:

  DynamoStore - the deployed one. One table, one GSI, on-demand capacity.
  LocalStore  - a JSON file on disk, so the dev server, the tests and a laptop
                with no AWS credentials exercise the same access patterns.

Keeping both behind `Store` is what lets `scripts/serve_local.py` run the real
Lambda handlers unmodified.

Key layout (PK / SK / GSI1PK):

  USER#<sub>      PROFILE                     -
  USER#<sub>      ITEM#<ulid>                 BATCH#<skeleton>   <- shelf item
  USER#<sub>      ALERT#<ts>#<ulid>           -
  BATCH#<skel>    NSQ#<month>#<hash>          DRUG#<generic>     <- flagged batch
  SOURCE#CDSCO    DOC#<urlhash>               -
  JOB#<ulid>      META                        -

The one query the whole product rests on is GSI1PK = BATCH#<skeleton>:
"a batch was just flagged - whose shelf is it on?"
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
from typing import Any, Iterable

SEP = "|#|"  # never appears in a PK or SK


def pk_user(sub: str) -> str:
    return f"USER#{sub}"


def pk_batch(skeleton: str) -> str:
    return f"BATCH#{skeleton}"


def gsi_batch(skeleton: str) -> str:
    return f"BATCH#{skeleton}"


def gsi_drug(generic: str) -> str:
    return f"DRUG#{(generic or '').strip().lower()}"


class Store:
    """Minimal single-table interface. Every method is one DynamoDB call."""

    def put(self, item: dict) -> dict:
        raise NotImplementedError

    def batch_put(self, items: Iterable[dict]) -> int:
        raise NotImplementedError

    def get(self, pk: str, sk: str) -> dict | None:
        raise NotImplementedError

    def query(
        self, pk: str, sk_prefix: str = "", limit: int | None = None, descending: bool = False
    ) -> list[dict]:
        raise NotImplementedError

    def query_gsi1(self, gsi1pk: str, limit: int | None = None) -> list[dict]:
        raise NotImplementedError

    def delete(self, pk: str, sk: str) -> bool:
        raise NotImplementedError

    def scan_prefix(self, pk_prefix: str, limit: int | None = None) -> list[dict]:
        """Only used by the index loader and admin tooling, never per-request."""
        raise NotImplementedError


# ------------------------------------------------------------------ local


class LocalStore(Store):
    """A JSON file pretending to be DynamoDB. Good enough to be honest with.

    Writes are serialised through a lock and land via a temp-file rename, so an
    interrupted dev server cannot leave a half-written state file behind.
    """

    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._items: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = {k: v for k, v in raw.items()}
        except (json.JSONDecodeError, OSError):
            # A corrupt dev-state file should not stop the server booting.
            self._items = {}

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _key(pk: str, sk: str) -> str:
        return f"{pk}{SEP}{sk}"

    def put(self, item: dict) -> dict:
        with self._lock:
            self._items[self._key(item["PK"], item["SK"])] = dict(item)
            self._flush()
        return item

    def batch_put(self, items: Iterable[dict]) -> int:
        n = 0
        with self._lock:
            for item in items:
                self._items[self._key(item["PK"], item["SK"])] = dict(item)
                n += 1
            self._flush()
        return n

    def get(self, pk: str, sk: str) -> dict | None:
        with self._lock:
            found = self._items.get(self._key(pk, sk))
            return dict(found) if found else None

    def query(
        self, pk: str, sk_prefix: str = "", limit: int | None = None, descending: bool = False
    ) -> list[dict]:
        with self._lock:
            rows = [
                dict(v)
                for k, v in self._items.items()
                if k.startswith(pk + SEP) and v.get("SK", "").startswith(sk_prefix)
            ]
        rows.sort(key=lambda r: r.get("SK", ""), reverse=descending)
        return rows[:limit] if limit else rows

    def query_gsi1(self, gsi1pk: str, limit: int | None = None) -> list[dict]:
        with self._lock:
            rows = [dict(v) for v in self._items.values() if v.get("GSI1PK") == gsi1pk]
        rows.sort(key=lambda r: (r.get("PK", ""), r.get("SK", "")))
        return rows[:limit] if limit else rows

    def delete(self, pk: str, sk: str) -> bool:
        with self._lock:
            existed = self._items.pop(self._key(pk, sk), None) is not None
            if existed:
                self._flush()
        return existed

    def scan_prefix(self, pk_prefix: str, limit: int | None = None) -> list[dict]:
        with self._lock:
            rows = [dict(v) for v in self._items.values() if v.get("PK", "").startswith(pk_prefix)]
        return rows[:limit] if limit else rows


# --------------------------------------------------------------- dynamodb


class DynamoStore(Store):
    def __init__(self, table_name: str, gsi_name: str = "GSI1"):
        import boto3  # imported lazily: the local driver must not need it

        self.table_name = table_name
        self.gsi_name = gsi_name
        self._table = boto3.resource("dynamodb").Table(table_name)

    def put(self, item: dict) -> dict:
        self._table.put_item(Item=_clean(item))
        return item

    def batch_put(self, items: Iterable[dict]) -> int:
        n = 0
        with self._table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for item in items:
                batch.put_item(Item=_clean(item))
                n += 1
        return n

    def get(self, pk: str, sk: str) -> dict | None:
        resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        return resp.get("Item")

    def query(
        self, pk: str, sk_prefix: str = "", limit: int | None = None, descending: bool = False
    ) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        cond = Key("PK").eq(pk)
        if sk_prefix:
            cond = cond & Key("SK").begins_with(sk_prefix)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": cond,
            "ScanIndexForward": not descending,
        }
        if limit:
            kwargs["Limit"] = limit
        return self._paginate(self._table.query, kwargs, limit)

    def query_gsi1(self, gsi1pk: str, limit: int | None = None) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        kwargs: dict[str, Any] = {
            "IndexName": self.gsi_name,
            "KeyConditionExpression": Key("GSI1PK").eq(gsi1pk),
        }
        if limit:
            kwargs["Limit"] = limit
        return self._paginate(self._table.query, kwargs, limit)

    def delete(self, pk: str, sk: str) -> bool:
        resp = self._table.delete_item(Key={"PK": pk, "SK": sk}, ReturnValues="ALL_OLD")
        return bool(resp.get("Attributes"))

    def scan_prefix(self, pk_prefix: str, limit: int | None = None) -> list[dict]:
        from boto3.dynamodb.conditions import Attr

        kwargs: dict[str, Any] = {"FilterExpression": Attr("PK").begins_with(pk_prefix)}
        return self._paginate(self._table.scan, kwargs, limit)

    @staticmethod
    def _paginate(op, kwargs: dict, limit: int | None) -> list[dict]:
        out: list[dict] = []
        while True:
            resp = op(**kwargs)
            out.extend(resp.get("Items", []))
            token = resp.get("LastEvaluatedKey")
            if not token or (limit and len(out) >= limit):
                break
            kwargs["ExclusiveStartKey"] = token
        return out[:limit] if limit else out


def _clean(item: dict) -> dict:
    """DynamoDB rejects empty strings in key attributes and floats anywhere."""
    out = {}
    for k, v in item.items():
        if v is None:
            continue
        if isinstance(v, float):
            from decimal import Decimal

            out[k] = Decimal(str(round(v, 6)))
        elif isinstance(v, dict):
            out[k] = _clean(v)
        elif isinstance(v, list):
            out[k] = [_clean(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ factory

_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """Pick a driver from the environment, once per process.

    BW_STORE=dynamodb + BW_TABLE=<name>  -> DynamoStore
    anything else                        -> LocalStore at BW_LOCAL_DIR/state.json
    """
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is not None:
            return _store
        kind = os.environ.get("BW_STORE", "").lower()
        table = os.environ.get("BW_TABLE", "")
        if kind == "dynamodb" or (not kind and table):
            _store = DynamoStore(table or "batchwatch")
        else:
            base = os.environ.get("BW_LOCAL_DIR") or str(
                pathlib.Path(__file__).resolve().parents[4] / ".local"
            )
            _store = LocalStore(pathlib.Path(base) / "state.json")
        return _store


def reset_store() -> None:
    """Drop the cached driver. Tests use this; production never calls it."""
    global _store
    with _store_lock:
        _store = None
