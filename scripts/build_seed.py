"""Turn the PDFs in data/pdfs/ into data/nsq_seed.jsonl.

    python scripts/build_seed.py                # heuristic column mapping
    python scripts/build_seed.py --use-bedrock  # let Claude map the columns

The heuristic path reads the header row and maps columns by keyword. It works
on tidy layouts and costs nothing. The Bedrock path hands each row to Claude
with a strict output schema and handles the layouts that change between months
and between state regulators - which is most of them.

Run --dry-run first on a couple of documents to see how many rows come out
before spending anything.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functions" / "common" / "python"))

from batchwatch_common import bedrock  # noqa: E402
from batchwatch_common.cdsco import guess_alert_month  # noqa: E402
from batchwatch_common.ingest import (  # noqa: E402
    extract_rows,
    normalise_rows,
    to_canonical,
)

BATCH_SIZE = 40


def load_manifest() -> dict:
    path = ROOT / "data" / "pdf_manifest.json"
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {e["file"]: e for e in entries.values() if "file" in e}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdfs", default=str(ROOT / "data" / "pdfs"))
    ap.add_argument("--out", default=str(ROOT / "data" / "nsq_seed.jsonl"))
    ap.add_argument("--use-bedrock", action="store_true", help="use Claude for column mapping")
    ap.add_argument("--no-textract", action="store_true", help="never fall back to Textract")
    ap.add_argument("--limit", type=int, default=0, help="only process this many PDFs")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = ap.parse_args()

    pdf_dir = pathlib.Path(args.pdfs)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if args.limit:
        pdfs = pdfs[: args.limit]

    if not pdfs:
        print(f"no PDFs in {pdf_dir}")
        print("run: python scripts/download_cdsco.py --months 18")
        print("or save the monthly alert PDFs there by hand.")
        return 1

    if args.use_bedrock and not bedrock.available():
        print(f"--use-bedrock asked for, but Bedrock is not reachable: {bedrock.status()['error']}")
        print("falling back to the heuristic mapper")
        args.use_bedrock = False

    manifest = load_manifest()
    all_rows: list[dict] = []
    paths = Counter()
    report: list[tuple[str, int, int, str]] = []

    for pdf in pdfs:
        meta = manifest.get(pdf.name, {})
        alert_month = meta.get("alert_month") or guess_alert_month(pdf.name) or ""
        source_url = meta.get("url", "")

        try:
            raw = extract_rows(pdf.read_bytes(), use_textract=not args.no_textract)
        except Exception as exc:  # noqa: BLE001
            print(f"  {pdf.name}: extraction failed - {type(exc).__name__}: {exc}")
            report.append((pdf.name, 0, 0, "extract-failed"))
            continue

        mapped: list[dict] = []
        used = set()
        context = f"CDSCO drug alert, {alert_month or 'month unknown'}, file {pdf.name}"
        for start in range(0, len(raw), BATCH_SIZE):
            chunk_mapped, path = normalise_rows(
                raw[start : start + BATCH_SIZE], context=context, prefer_model=args.use_bedrock
            )
            mapped.extend(chunk_mapped)
            used.add(path)

        canonical = to_canonical(mapped, alert_month=alert_month, source_url=source_url)
        all_rows.extend(canonical)
        for p in used:
            paths[p] += 1
        report.append((pdf.name, len(raw), len(canonical), "+".join(sorted(used))))
        print(f"  {pdf.name:44} {len(raw):5} raw -> {len(canonical):5} rows  [{'+'.join(sorted(used))}]")

    # Two documents can list the same batch; keep one row per identity.
    seen: set[tuple] = set()
    deduped = []
    for row in all_rows:
        key = (row["batch_skeleton"], row["drug_name"].lower(), row["alert_month"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    months = sorted({r["alert_month"] for r in deduped if r["alert_month"]})
    print()
    print(f"documents   {len(pdfs)}")
    print(f"rows        {len(deduped)} ({len(all_rows) - len(deduped)} duplicates dropped)")
    print(f"months      {len(months)}" + (f" ({months[0]} .. {months[-1]})" if months else ""))
    print(f"mapper      {dict(paths)}")

    weak = [name for name, raw_n, out_n, _ in report if raw_n > 10 and out_n == 0]
    if weak:
        print(f"\n{len(weak)} document(s) produced no usable rows:")
        for name in weak[:10]:
            print(f"  {name}")
        print("Those are usually scans or an unfamiliar layout - try --use-bedrock.")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    if not deduped:
        print("\nno rows extracted - not overwriting the existing seed file")
        return 1

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in deduped:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(deduped)} rows -> {out}")
    print("next: python scripts/load_seed.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
