"""Download CDSCO monthly NSQ alert PDFs to data/pdfs/.

    python scripts/download_cdsco.py --list           # see what it finds first
    python scripts/download_cdsco.py --months 18

Run this locally, not in Lambda. The site has no machine-readable index and
reorganises periodically, so treat a thin result as a scraper problem rather
than as "there were no alerts": use --list, and fall back to saving the PDFs by
hand into data/pdfs/. Having the corpus is a day-one necessity; automating the
fetch is a day-three nicety.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functions" / "common" / "python"))

from batchwatch_common.cdsco import discover, fetch, guess_alert_month  # noqa: E402
from batchwatch_common.ids import sha256_hex  # noqa: E402

OUT_DIR = ROOT / "data" / "pdfs"
MANIFEST = ROOT / "data" / "pdf_manifest.json"


def load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--months", type=int, default=18, help="how many documents to keep")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--list", action="store_true", help="list what was found, download nothing")
    ap.add_argument("--all-pdfs", action="store_true", help="do not filter to alert-looking links")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between downloads")
    args = ap.parse_args()

    print("searching cdsco.gov.in for alert PDFs ...")
    links = discover(alerts_only=not args.all_pdfs)
    if not links:
        print("\nnothing found. The listing pages have probably moved.")
        print("Open https://cdsco.gov.in and save the monthly alert PDFs into data/pdfs/ by hand,")
        print("then run: python scripts/build_seed.py")
        return 1

    print(f"found {len(links)} candidate documents\n")
    for link in links[: args.months]:
        print(f"  {link['alert_month'] or '????-??'}  {link['label'][:60] or link['url'][-60:]}")

    if args.list:
        return 0

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    downloaded = 0

    print()
    for link in links[: args.months]:
        url = link["url"]
        key = sha256_hex(url, 16)
        month = link["alert_month"] or guess_alert_month(url) or "unknown"
        target = out_dir / f"{month}-{key}.pdf"

        if target.exists():
            print(f"  have    {target.name}")
            continue
        try:
            data = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED  {url}\n          {type(exc).__name__}: {exc}")
            continue

        if not data.startswith(b"%PDF"):
            print(f"  skip    {url} (not a PDF - the site returned {len(data)} bytes of something else)")
            continue

        target.write_bytes(data)
        manifest[key] = {
            "url": url,
            "file": target.name,
            "alert_month": month,
            "label": link["label"],
            "bytes": len(data),
        }
        downloaded += 1
        print(f"  saved   {target.name}  ({len(data) // 1024}KB)")
        time.sleep(args.delay)

    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{downloaded} new documents in {out_dir}")
    print("next: python scripts/build_seed.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
