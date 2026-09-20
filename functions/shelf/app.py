"""Shelf CRUD and the alert feed.

The shelf is the point of the project: a scan is a lookup, but a saved shelf is
what lets a recall published next month reach the person who already bought the
medicine.
"""
from __future__ import annotations

from batchwatch_common.http import (
    HttpError,
    handler,
    method_of,
    ok,
    parse_body,
    path_params,
    query_params,
    response,
    user_sub,
)
from batchwatch_common.normalise import plausible_batch
from batchwatch_common.repo import (
    add_shelf_item,
    delete_shelf_item,
    list_alerts,
    list_shelf,
    load_index,
    update_shelf_verdict,
)
from batchwatch_common.store import get_store, pk_user
from batchwatch_common.verdict import build_verdict


def _route(event: dict) -> str:
    """Normalise the route across HTTP API, REST API and the local server."""
    key = event.get("routeKey") or ""
    if key and key != "$default":
        return key
    ctx = event.get("requestContext") or {}
    path = (ctx.get("http") or {}).get("path") or event.get("rawPath") or event.get("path") or "/"
    return f"{method_of(event)} {path}"


@handler
def lambda_handler(event: dict, context=None) -> dict:
    sub = user_sub(event)
    route = _route(event)
    method = method_of(event)

    if "/alerts" in route:
        if method != "GET":
            raise HttpError(405, f"{method} not allowed on /alerts")
        return _get_alerts(sub, event)

    if method == "GET":
        return _get_shelf(sub, event)
    if method == "POST":
        return _post_shelf(sub, event)
    if method == "DELETE":
        return _delete_shelf(sub, event)
    raise HttpError(405, f"{method} not allowed on /shelf")


def _get_shelf(sub: str, event: dict) -> dict:
    """List the shelf, re-checking each item against the current corpus.

    Re-checking on read is what makes the shelf honest: the corpus moves under
    it, so a stored verdict goes stale the moment a new alert lands.
    """
    recheck = (query_params(event).get("recheck") or "1") != "0"
    items = list_shelf(sub)
    index = load_index() if recheck else None

    out = []
    for item in items:
        entry = dict(item)
        if index is not None and item.get("batch_norm"):
            verdict = build_verdict(
                {
                    "batch": item.get("batch_norm", ""),
                    "drug_name": item.get("drug_name", ""),
                    "manufacturer": item.get("manufacturer", ""),
                    "exp_date": item.get("exp_date", ""),
                },
                index,
                allow_adjudication=False,
            )
            entry["verdict"] = verdict["verdict"]
            entry["tone"] = verdict["tone"]
            entry["severity"] = verdict["severity"]
            entry["match"] = verdict["match"]
            if verdict["verdict"] != item.get("last_verdict"):
                update_shelf_verdict(item, verdict["verdict"])
        out.append(entry)

    out.sort(key=lambda i: i.get("added_at", ""), reverse=True)
    return ok({"items": out, "count": len(out)})


def _post_shelf(sub: str, event: dict) -> dict:
    body = parse_body(event)
    batch = (body.get("batch") or body.get("batch_raw") or "").strip()
    if not batch:
        raise HttpError(400, "batch is required")
    if not plausible_batch(batch):
        raise HttpError(400, f"'{batch}' does not look like a batch number")
    if not (body.get("drug_name") or "").strip():
        raise HttpError(400, "drug_name is required - a batch code alone cannot be matched safely")

    item = add_shelf_item(sub, body)
    index = load_index()
    verdict = build_verdict(
        {
            "batch": item["batch_norm"],
            "drug_name": item["drug_name"],
            "manufacturer": item["manufacturer"],
            "exp_date": item["exp_date"],
        },
        index,
        allow_adjudication=False,
    )
    update_shelf_verdict(item, verdict["verdict"])
    item["last_verdict"] = verdict["verdict"]
    return response(201, {"item": item, "verdict": verdict})


def _delete_shelf(sub: str, event: dict) -> dict:
    item_id = (path_params(event).get("id") or "").strip()
    if not item_id:
        raise HttpError(400, "item id is required")
    if not delete_shelf_item(sub, item_id):
        raise HttpError(404, "no such item on your shelf")
    return ok({"deleted": item_id})


def _get_alerts(sub: str, event: dict) -> dict:
    limit = min(int(query_params(event).get("limit") or 50), 200)
    alerts = list_alerts(sub, limit=limit)
    unread = sum(1 for a in alerts if not a.get("read"))

    if (query_params(event).get("mark_read") or "") == "1":
        store = get_store()
        for alert in alerts:
            if not alert.get("read"):
                alert["read"] = True
                store.put({**alert, "PK": pk_user(sub)})
        unread = 0

    return ok({"alerts": alerts, "count": len(alerts), "unread": unread})
