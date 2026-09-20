"""POST /admin/ingest - trigger the monthly pipeline by hand.

Needed for the demo: hold a month of alerts back from the seed, scan a strip
(clear), then call this endpoint and watch the alert arrive on the shelf.

Three modes, in order of preference:
  rows        ingest canonical rows sent in the request body
  month       ingest a month held back in the local seed file
  (default)   start the Step Functions state machine, if one is configured
"""
from __future__ import annotations

import json
import os
import pathlib

from batchwatch_common.http import HttpError, handler, ok, parse_body, require_admin
from batchwatch_common.ids import ulid
from batchwatch_common.ingest import ingest_rows
from batchwatch_common.normalise import canonical_row, row_is_usable
from batchwatch_common.repo import corpus_stats, load_index

STATE_MACHINE_ARN = os.environ.get("BW_STATE_MACHINE_ARN", "")
HOLDBACK_FILE = os.environ.get(
    "BW_HOLDBACK_FILE",
    str(pathlib.Path(__file__).resolve().parents[2] / "data" / "nsq_holdback.jsonl"),
)


@handler
def lambda_handler(event: dict, context=None) -> dict:
    require_admin(event)
    body = parse_body(event)

    if body.get("rows"):
        rows = [canonical_row(r) for r in body["rows"]]
        rows = [r for r in rows if row_is_usable(r)]
        if not rows:
            raise HttpError(400, "none of the rows supplied had a usable batch number")
        return ok(_ingest(rows, body))

    month = (body.get("month") or "").strip()
    if month:
        rows = _rows_for_month(month)
        if not rows:
            raise HttpError(
                404,
                f"no held-back rows for {month} in {HOLDBACK_FILE}",
                hint="run scripts/load_seed.py --holdback-month to create one",
            )
        return ok(_ingest(rows, body))

    if not STATE_MACHINE_ARN:
        raise HttpError(
            400,
            "send 'rows' or 'month', or configure BW_STATE_MACHINE_ARN to start "
            "the full fetch/extract/normalise/fanout pipeline",
        )

    import boto3

    run_id = ulid()
    execution = boto3.client("stepfunctions").start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=f"bw-{run_id}",
        input=json.dumps({"run_id": run_id, **{k: v for k, v in body.items() if k != "rows"}}),
    )
    return ok(
        {
            "started": True,
            "run_id": run_id,
            "execution_arn": execution["executionArn"],
            "note": "watch it run in the Step Functions console",
        }
    )


def _rows_for_month(month: str) -> list[dict]:
    path = pathlib.Path(HOLDBACK_FILE)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not month or row.get("alert_month") == month:
            rows.append(canonical_row(row))
    return [r for r in rows if row_is_usable(r)]


def _ingest(rows: list[dict], body: dict) -> dict:
    before = corpus_stats(load_index())["rows"]
    result = ingest_rows(
        rows,
        deep=bool(body.get("deep", True)),
        notify=bool(body.get("notify", True)),
    )
    after = corpus_stats(load_index(force=True))["rows"]
    result["corpus_rows_before"] = before
    result["corpus_rows_after"] = after
    return result
