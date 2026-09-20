"""Load a JSONL corpus into the table (DynamoDB or the local store).

    python scripts/load_seed.py                          # everything
    python scripts/load_seed.py --holdback-month 2026-08 # keep a month back

The hold-back is the demo: keep the most recent month out of the database, scan
a strip from it (comes back clear), then POST /admin/ingest with that month and
watch the alert land on the shelf.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functions" / "common" / "python"))

from batchwatch_common.normalise import canonical_row, row_is_usable  # noqa: E402
from batchwatch_common.repo import corpus_stats, load_index, save_nsq_rows  # noqa: E402


def read_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"  skipping line {n}: {exc.msg}")
    return rows


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", default=str(ROOT / "data" / "nsq_seed.jsonl"))
    ap.add_argument(
        "--holdback-month",
        default="",
        help="keep this alert month out of the database and write it to data/nsq_holdback.jsonl",
    )
    ap.add_argument("--holdback-file", default=str(ROOT / "data" / "nsq_holdback.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    path = pathlib.Path(args.file)
    if not path.exists():
        print(f"no such file: {path}")
        print("run: python scripts/make_sample_seed.py")
        return 1

    raw = read_jsonl(path)
    rows = [canonical_row(r) for r in raw]
    usable = [r for r in rows if row_is_usable(r)]
    dropped = len(rows) - len(usable)

    held: list[dict] = []
    if args.holdback_month:
        held = [r for r in usable if r.get("alert_month") == args.holdback_month]
        usable = [r for r in usable if r.get("alert_month") != args.holdback_month]
        write_jsonl(pathlib.Path(args.holdback_file), held)

    if args.limit:
        usable = usable[: args.limit]

    saved = save_nsq_rows(usable)
    stats = corpus_stats(load_index(force=True))

    print(f"read     {len(raw)} rows from {path.name}")
    if dropped:
        print(f"dropped  {dropped} without a usable batch number")
    if args.holdback_month:
        print(f"held     {len(held)} rows for {args.holdback_month} -> {args.holdback_file}")
    print(f"loaded   {saved} rows")
    print(
        f"corpus   {stats['rows']} rows, {stats['distinct_batches']} batches, "
        f"{stats['alert_months']} months ({stats['earliest_alert_month']} .. "
        f"{stats['latest_alert_month']})"
    )
    if stats["corpus_is_synthetic"]:
        print("         NOTE: every row is synthetic sample data, not real CDSCO alerts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
