"""End-to-end tests over the real Lambda handlers.

These build API Gateway HTTP API v2 events and call the handlers directly, the
same way scripts/serve_local.py does, against a throwaway LocalStore. The last
test walks the demo: scan a strip that comes back clear, ingest the month that
flags it, and watch the alert appear on the shelf.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEVICE = "test-device-0001"
ADMIN_KEY = "test-admin-key"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"bw_test_{name}", ROOT / "functions" / name / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.lambda_handler


def event(
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
    params: dict | None = None,
    headers: dict | None = None,
) -> dict:
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "headers": {"x-device-id": DEVICE, **(headers or {})},
        "queryStringParameters": query or {},
        "pathParameters": params or {},
        "body": json.dumps(body) if body is not None else "",
        "isBase64Encoded": False,
        "requestContext": {"http": {"method": method, "path": path}},
    }


def payload(result: dict) -> dict:
    return json.loads(result["body"])


@pytest.fixture()
def api(tmp_path, monkeypatch, seed_rows):
    """A live API over a throwaway store, seeded with all but the last month."""
    monkeypatch.setenv("BW_STORE", "local")
    monkeypatch.setenv("BW_LOCAL_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BW_ALLOW_DEVICE_ID", "1")
    monkeypatch.setenv("BW_ADMIN_KEY", ADMIN_KEY)
    monkeypatch.setenv("BW_BEDROCK", "off")
    monkeypatch.setenv("BW_SES_FROM", "")

    from batchwatch_common import bedrock, repo, store

    bedrock.reset()
    store.reset_store()
    repo.invalidate_index()

    months = sorted({r["alert_month"] for r in seed_rows})
    holdback_month = months[-1]
    loaded = [r for r in seed_rows if r["alert_month"] != holdback_month]
    held = [r for r in seed_rows if r["alert_month"] == holdback_month]
    repo.save_nsq_rows(loaded)
    repo.invalidate_index()

    handlers = {name: _load(name) for name in ("scan", "shelf", "search", "pharmacy", "admin")}
    yield {
        "h": handlers,
        "held": held,
        "loaded": loaded,
        "holdback_month": holdback_month,
    }

    store.reset_store()
    repo.invalidate_index()


# --------------------------------------------------------------- stats/search


def test_stats_reports_the_corpus(api):
    body = payload(api["h"]["search"](event("GET", "/stats"), None))
    assert body["rows"] == len(api["loaded"])
    assert body["latest_alert_month"] < api["holdback_month"]
    assert body["corpus_is_synthetic"] is True
    assert "disclaimer" in body


def test_search_by_batch_finds_a_flagged_row(api):
    row = api["loaded"][0]
    body = payload(
        api["h"]["search"](event("GET", "/search", query={"q": row["batch_norm"]}), None)
    )
    assert body["mode"] == "batch"
    assert body["results"]
    assert body["results"][0]["batch_norm"] == row["batch_norm"]


def test_search_by_drug_name(api):
    body = payload(
        api["h"]["search"](event("GET", "/search", query={"q": "paracetamol"}), None)
    )
    assert body["mode"] == "text"
    assert all("paracetamol" in r["generic"] for r in body["results"])


def test_search_rejects_a_too_short_query(api):
    result = api["h"]["search"](event("GET", "/search", query={"q": "ab"}), None)
    assert result["statusCode"] == 400


# ------------------------------------------------------------------- scan


def test_scan_text_flags_a_listed_batch(api):
    row = api["loaded"][0]
    label = (
        f"{row['drug_name']}\n"
        f"B.No. {row['batch_norm']}\n"
        f"MFG {row['mfg_date']}  EXP {row['exp_date']}\n"
        f"Mfd. by: {row['manufacturer_raw']}"
    )
    body = payload(api["h"]["scan"](event("POST", "/scan", {"text": label}), None))
    assert body["verdict"] == "FLAGGED"
    assert body["tone"] == "red"
    assert body["match"]["batch_norm"] == row["batch_norm"]
    assert body["advice"]["en"]
    assert body["advice"]["hi"]
    assert body["advice"]["ta"]
    assert "not a certification" in body["disclaimer"].lower()


def test_scan_text_clears_an_unlisted_batch(api):
    body = payload(
        api["h"]["scan"](
            event(
                "POST",
                "/scan",
                {"text": "Paracetamol Tablets IP 650mg\nB.No. ZZ9999Q\nEXP 12/2029"},
            ),
            None,
        )
    )
    assert body["verdict"] == "NO_MATCH"
    assert body["tone"] == "green"
    # The green state must never claim the medicine is safe.
    assert "safe" not in body["headline"].lower()


def test_scan_without_a_batch_number_says_so(api):
    body = payload(
        api["h"]["scan"](event("POST", "/scan", {"text": "some illegible smudge"}), None)
    )
    assert body["verdict"] == "UNREADABLE"
    assert body["match"] is None


def test_scan_requires_an_image_or_text(api):
    result = api["h"]["scan"](event("POST", "/scan", {}), None)
    assert result["statusCode"] == 400


def test_scan_rejects_a_bad_image(api):
    result = api["h"]["scan"](event("POST", "/scan", {"image": "not base64!!"}), None)
    assert result["statusCode"] == 400


def test_scan_rejects_an_unsupported_media_type(api):
    import base64

    result = api["h"]["scan"](
        event(
            "POST",
            "/scan",
            {"image": base64.b64encode(b"x" * 64).decode(), "media_type": "image/tiff"},
        ),
        None,
    )
    assert result["statusCode"] == 400


def test_scan_with_an_image_says_so_when_vision_is_unavailable(api):
    """BW_BEDROCK is off in these tests, so the image path has nowhere to go."""
    import base64

    result = api["h"]["scan"](
        event("POST", "/scan", {"image": base64.b64encode(b"\xff\xd8\xff" + b"x" * 64).decode()}),
        None,
    )
    assert result["statusCode"] == 503
    body = payload(result)
    assert "type the label text" in body["error"]
    assert body["bedrock"]["available"] is False


def test_scan_falls_back_to_the_typed_text_when_vision_is_unavailable(api):
    """An image plus typed text still produces a verdict with no model at all."""
    import base64

    row = api["loaded"][0]
    result = api["h"]["scan"](
        event(
            "POST",
            "/scan",
            {
                "image": base64.b64encode(b"\xff\xd8\xff" + b"x" * 64).decode(),
                "text": f"{row['drug_name']}\nB.No. {row['batch_norm']}\nEXP {row['exp_date']}",
            },
        ),
        None,
    )
    assert result["statusCode"] == 200
    body = payload(result)
    assert body["verdict"] == "FLAGGED"
    assert body["extracted"]["source"] == "text-parser"


# ------------------------------------------------------------------ shelf


def test_shelf_add_list_and_delete(api):
    row = api["loaded"][3]
    created = api["h"]["shelf"](
        event(
            "POST",
            "/shelf",
            {
                "drug_name": row["drug_name"],
                "batch": row["batch_norm"],
                "manufacturer": row["manufacturer_raw"],
                "exp_date": row["exp_date"],
            },
        ),
        None,
    )
    assert created["statusCode"] == 201
    item = payload(created)["item"]
    assert payload(created)["verdict"]["verdict"] == "FLAGGED"

    listed = payload(api["h"]["shelf"](event("GET", "/shelf"), None))
    assert listed["count"] == 1
    assert listed["items"][0]["item_id"] == item["item_id"]

    deleted = api["h"]["shelf"](
        event("DELETE", "/shelf/{id}", params={"id": item["item_id"]}), None
    )
    assert deleted["statusCode"] == 200
    assert payload(api["h"]["shelf"](event("GET", "/shelf"), None))["count"] == 0


def test_shelf_rejects_a_batch_with_no_drug_name(api):
    result = api["h"]["shelf"](event("POST", "/shelf", {"batch": "KP4021H"}), None)
    assert result["statusCode"] == 400
    assert "drug_name" in payload(result)["error"]


def test_shelf_requires_identity(api):
    anonymous = event("POST", "/shelf", {"batch": "KP4021H", "drug_name": "x"})
    anonymous["headers"] = {}
    result = api["h"]["shelf"](anonymous, None)
    assert result["statusCode"] == 401


# ---------------------------------------------------------------- pharmacy


def test_pharmacy_bulk_check_groups_by_severity(api):
    flagged = api["loaded"][:3]
    lines = ["drug,batch,manufacturer,expiry"]
    for row in flagged:
        lines.append(
            f"{row['drug_name']},{row['batch_norm']},{row['manufacturer_raw'].replace(',', ' ')},{row['exp_date']}"
        )
    lines.append("Paracetamol Tablets IP 500mg,ZZ9999Q,Some Other Pharma Ltd,2029-12")
    lines.append("Nothing Useful Here,,,")

    result = api["h"]["pharmacy"](
        event("POST", "/pharmacy/check", {"csv": "\n".join(lines)}), None
    )
    assert result["statusCode"] == 201
    body = payload(result)
    assert body["counts"]["FLAGGED"] == 3
    assert body["counts"]["NO_MATCH"] == 1
    assert body["counts"]["SKIPPED"] == 1
    # Flagged rows sort to the top so a chemist reads the worst news first.
    assert body["results"][0]["verdict"] == "FLAGGED"

    fetched = payload(
        api["h"]["pharmacy"](
            event("GET", "/pharmacy/check/{id}", params={"id": body["job_id"]}), None
        )
    )
    assert fetched["job_id"] == body["job_id"]
    assert fetched["counts"] == body["counts"]


def test_pharmacy_job_is_not_readable_by_another_device(api):
    body = payload(
        api["h"]["pharmacy"](
            event("POST", "/pharmacy/check", {"csv": "drug,batch\nParacetamol 650mg,KP4021H"}),
            None,
        )
    )
    other = event("GET", "/pharmacy/check/{id}", params={"id": body["job_id"]})
    other["headers"] = {"x-device-id": "someone-else"}
    assert api["h"]["pharmacy"](other, None)["statusCode"] == 403


# ------------------------------------------------------- the retroactive loop


def test_admin_ingest_requires_a_key(api):
    result = api["h"]["admin"](event("POST", "/admin/ingest", {"rows": []}), None)
    assert result["statusCode"] == 403


def test_a_recall_published_later_reaches_the_shelf(api):
    """The whole product, in one test.

    Save a medicine that is clean today, publish the month that flags it, and
    assert the alert arrives - without the user doing anything.
    """
    future = api["held"][0]

    # 1. It is on my shelf, and today it is not flagged.
    created = api["h"]["shelf"](
        event(
            "POST",
            "/shelf",
            {
                "drug_name": future["drug_name"],
                "batch": future["batch_norm"],
                "manufacturer": future["manufacturer_raw"],
                "exp_date": future["exp_date"],
            },
        ),
        None,
    )
    assert payload(created)["verdict"]["verdict"] == "NO_MATCH"
    item_id = payload(created)["item"]["item_id"]

    assert payload(api["h"]["shelf"](event("GET", "/alerts"), None))["count"] == 0

    # 2. The regulator publishes the month that flags it.
    ingest = api["h"]["admin"](
        event(
            "POST",
            "/admin/ingest",
            {"rows": api["held"], "notify": False},
            headers={"x-admin-key": ADMIN_KEY},
        ),
        None,
    )
    assert ingest["statusCode"] == 200
    result = payload(ingest)
    assert result["rows_saved"] == len(api["held"])
    assert result["alerts_created"] >= 1

    # 3. The alert is waiting, without the user scanning anything again.
    alerts = payload(api["h"]["shelf"](event("GET", "/alerts"), None))
    assert alerts["count"] >= 1
    assert alerts["unread"] >= 1
    mine = [a for a in alerts["alerts"] if a["item_id"] == item_id]
    assert mine, "the alert did not reach the shelf item that holds this batch"
    assert mine[0]["batch_norm"] == future["batch_norm"]
    assert mine[0]["severity"] in ("CRITICAL", "HIGH", "MODERATE", "LOW")
    assert mine[0]["failure_reason"]

    # 4. The shelf now shows it as flagged.
    shelf = payload(api["h"]["shelf"](event("GET", "/shelf"), None))
    assert shelf["items"][0]["verdict"] == "FLAGGED"


def test_ingesting_the_same_month_twice_does_not_double_alert(api):
    future = api["held"][0]
    api["h"]["shelf"](
        event(
            "POST",
            "/shelf",
            {
                "drug_name": future["drug_name"],
                "batch": future["batch_norm"],
                "manufacturer": future["manufacturer_raw"],
                "exp_date": future["exp_date"],
            },
        ),
        None,
    )
    admin_event = lambda: event(  # noqa: E731
        "POST",
        "/admin/ingest",
        {"rows": api["held"], "notify": False},
        headers={"x-admin-key": ADMIN_KEY},
    )
    first = payload(api["h"]["admin"](admin_event(), None))["alerts_created"]
    second = payload(api["h"]["admin"](admin_event(), None))["alerts_created"]
    assert first >= 1
    assert second == 0, "re-ingesting a month alerted the same person twice"
