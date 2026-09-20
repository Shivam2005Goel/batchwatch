"""Prove a deployment actually works, end to end, against any base URL.

    python scripts/verify_deploy.py                                  # local server
    python scripts/verify_deploy.py --base https://abc.execute-api.ap-south-1.amazonaws.com/dev \
                                    --admin-key "$ADMIN_KEY"

Walks the whole product in order and prints a pass/fail line for each step:
stats, search, scan-before, save, ingest the held-back month, alert arrives,
shelf turns red, pharmacy bulk check, cleanup.

The step that matters is 6: an alert reaching a shelf item without the user
touching anything. If that passes on a deployed URL, the deployment is real.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]

PASS = "  PASS"
FAIL = "  FAIL"


class Client:
    def __init__(self, base: str, device: str, admin_key: str, token: str = ""):
        self.base = base.rstrip("/")
        self.device = device
        self.admin_key = admin_key
        self.token = token

    def call(self, method: str, path: str, body=None, admin: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        req.add_header("x-device-id", self.device)
        if admin:
            req.add_header("x-admin-key", self.admin_key)
        if self.token:
            req.add_header("authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw or "{}")
            except json.JSONDecodeError:
                return exc.code, {"error": raw[:300]}
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--admin-key", default="local-dev-key")
    ap.add_argument("--token", default="", help="Cognito id token, if RequireLogin=true")
    ap.add_argument("--holdback", default=str(ROOT / "data" / "nsq_holdback.jsonl"))
    ap.add_argument("--device", default=f"verify-{int(time.time())}")
    ap.add_argument("--keep", action="store_true", help="do not delete the shelf item afterwards")
    args = ap.parse_args()

    c = Client(args.base, args.device, args.admin_key, args.token)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        print(f"{PASS if ok else FAIL}  {name}{'  :: ' + detail if detail else ''}")
        if not ok:
            failures.append(name)
        return ok

    print(f"\nBatchWatch deployment check\n  base   {args.base}\n  device {args.device}\n")

    # 1 ------------------------------------------------------------- stats
    status, stats = c.call("GET", "/stats")
    if not check("1. GET /stats reachable", status == 200, stats.get("error", "")):
        print("\nCannot reach the API at all. Check the URL and that the stack deployed.")
        return 1
    print(
        f"        corpus {stats.get('rows', 0)} rows, "
        f"{stats.get('alert_months', 0)} months, latest {stats.get('latest_alert_month', '?')}"
    )
    bedrock = stats.get("bedrock", {})
    print(
        f"        bedrock available={bedrock.get('available')} "
        f"model={bedrock.get('model')} region={bedrock.get('region')}"
        + (f"\n        bedrock error: {bedrock['error']}" if bedrock.get("error") else "")
    )
    if stats.get("corpus_is_synthetic"):
        print("        NOTE corpus is synthetic sample data, not real CDSCO alerts")
    check("   corpus is loaded", stats.get("rows", 0) > 0, "run scripts/load_seed.py if 0")

    # 2 ------------------------------------------------------------ holdback
    path = pathlib.Path(args.holdback)
    if not path.exists():
        print(f"\n{FAIL}  no hold-back file at {path}")
        print("  run: python scripts/load_seed.py --holdback-month <YYYY-MM>")
        return 1
    held = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    target = next((h for h in held if h.get("severity") == "CRITICAL"), held[0])
    print(f"\n  demo medicine: {target['drug_name']}  batch {target['batch_norm']}")
    print(f"  will be flagged in {target['alert_month']} ({target['severity']})\n")

    # 3 -------------------------------------------------------- scan (clear)
    label = (
        f"{target['drug_name']}\nB.No. {target['batch_norm']}\n"
        f"MFG {target['mfg_date']}  EXP {target['exp_date']}\n"
        f"Mfd. by: {target['manufacturer_raw']}"
    )
    t0 = time.perf_counter()
    status, scan = c.call("POST", "/scan", {"text": label})
    ms = (time.perf_counter() - t0) * 1000
    check(
        "2. POST /scan reads the label and clears it",
        status == 200 and scan.get("verdict") == "NO_MATCH",
        f"{scan.get('verdict', scan.get('error'))} in {ms:.0f}ms",
    )

    # 4 ------------------------------------------------------------- shelf
    status, saved = c.call(
        "POST",
        "/shelf",
        {
            "drug_name": target["drug_name"],
            "batch": target["batch_norm"],
            "manufacturer": target["manufacturer_raw"],
            "exp_date": target["exp_date"],
        },
    )
    ok = status == 201
    item_id = saved.get("item", {}).get("item_id", "") if ok else ""
    check("3. POST /shelf saves it", ok, saved.get("error", "") or f"item {item_id[:12]}")
    if not item_id:
        print("\n  Cannot continue without a shelf item.")
        if status in (401, 403):
            print("  401/403 means the shelf routes need a Cognito token.")
            print("  Redeploy with RequireLogin=false, or pass --token <id token>.")
        return 1

    status, before = c.call("GET", "/alerts")
    check("4. GET /alerts is empty to start", status == 200 and before.get("count", -1) == 0,
          f"{before.get('count')} alerts")

    # 5 ------------------------------------------------------------ ingest
    t0 = time.perf_counter()
    status, ingest = c.call("POST", "/admin/ingest", {"rows": held, "notify": False}, admin=True)
    ms = (time.perf_counter() - t0) * 1000
    ok = status == 200 and ingest.get("alerts_created", 0) >= 1
    check(
        "5. POST /admin/ingest publishes the held-back month",
        ok,
        f"{ingest.get('rows_saved', 0)} rows, {ingest.get('alerts_created', 0)} alerts, {ms:.0f}ms"
        if status == 200
        else f"{status} {ingest.get('error')}",
    )
    if status == 403:
        print("  403 means the admin key is wrong - pass --admin-key <the AdminKey you deployed>")

    # 6 ------------------------------------------- THE ONE THAT MATTERS
    alert = None
    for attempt in range(6):
        status, after = c.call("GET", "/alerts")
        mine = [a for a in after.get("alerts", []) if a.get("item_id") == item_id]
        if mine:
            alert = mine[0]
            break
        time.sleep(1.5 * (attempt + 1))

    if check(
        "6. the alert reaches the shelf item with no further user action",
        alert is not None,
        f"{alert['severity']}: {alert['failure_reason']}" if alert else "no alert arrived",
    ):
        print(f"        >>> {alert['drug_name']}  batch {alert['batch_norm']}")

    # 7 ------------------------------------------------------ shelf re-check
    status, shelf = c.call("GET", "/shelf")
    mine = [i for i in shelf.get("items", []) if i.get("item_id") == item_id]
    verdict = mine[0].get("verdict") if mine else None
    ok = verdict == "FLAGGED"
    check("7. GET /shelf now reads FLAGGED", ok, str(verdict))
    if not ok and verdict == "NO_MATCH":
        print("        A warm read Lambda is serving a stale corpus. Check that the")
        print("        ingest wrote SOURCE#CDSCO / INDEX_VERSION to the table.")

    # 8 ------------------------------------------------------------ search
    status, found = c.call("GET", f"/search?q={target['batch_norm']}")
    check("8. GET /search finds the flagged batch", status == 200 and found.get("count", 0) >= 1,
          f"{found.get('count', 0)} results")

    # 9 ---------------------------------------------------------- pharmacy
    csv = "product,batch,manufacturer,expiry\n" + "\n".join(
        f"{h['drug_name']},{h['batch_norm']},{h['manufacturer_raw'].replace(',', ' ')},{h['exp_date']}"
        for h in held[:4]
    ) + "\nParacetamol Tablets IP 500mg,ZZ9999Q,Some Other Pharma Ltd,2029-12"
    status, job = c.call("POST", "/pharmacy/check", {"csv": csv})
    counts = job.get("counts", {})
    check("9. POST /pharmacy/check flags the stock list",
          status == 201 and counts.get("FLAGGED", 0) >= 1, json.dumps(counts))

    # 10 ------------------------------------------------------- an OCR miss
    damaged = target["batch_norm"].replace("4", "A", 1).replace("0", "O", 1)
    status, dmg = c.call(
        "POST",
        "/scan",
        {"text": f"{target['drug_name']}\nB.No. {damaged}\nEXP {target['exp_date']}\n"
                 f"Mfd. by: {target['manufacturer_raw']}"},
    )
    check(
        "10. a mis-read batch code is still caught",
        status == 200 and dmg.get("verdict") in ("FLAGGED", "UNCERTAIN"),
        f"read {damaged!r} vs real {target['batch_norm']!r} -> "
        f"{dmg.get('verdict')} @ {dmg.get('score')}",
    )

    if not args.keep and item_id:
        c.call("DELETE", f"/shelf/{item_id}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("All checks passed. The retroactive alert loop works on this deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
