"""Generate data/nsq_seed.jsonl - a SYNTHETIC stand-in for the CDSCO corpus.

Why this exists: the app has to be demoable before the real PDFs are parsed,
and it has to stay demoable if cdsco.gov.in is slow on Sunday morning.

Why the manufacturers are invented: publishing a fabricated quality failure
against a real pharmaceutical company is defamation, not test data. Every
generic drug name here is real (they belong to nobody); every manufacturer is
fictional; every row carries "synthetic": true, and the API reports the count
so the UI can say so out loud.

Replace this file with real data by running:
    python scripts/download_cdsco.py --months 18
    python scripts/build_seed.py --out data/nsq_seed.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "functions" / "common" / "python"))

from batchwatch_common.normalise import canonical_row  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Real generic molecules and forms - these identify no company.
PRODUCTS = [
    ("Paracetamol Tablets IP", ["500mg", "650mg"]),
    ("Amoxycillin Capsules IP", ["250mg", "500mg"]),
    ("Azithromycin Tablets IP", ["250mg", "500mg"]),
    ("Metformin Hydrochloride Tablets IP", ["500mg", "850mg", "1000mg"]),
    ("Amlodipine Tablets IP", ["2.5mg", "5mg", "10mg"]),
    ("Atorvastatin Tablets IP", ["10mg", "20mg", "40mg"]),
    ("Pantoprazole Gastro-resistant Tablets IP", ["20mg", "40mg"]),
    ("Cetirizine Hydrochloride Tablets IP", ["5mg", "10mg"]),
    ("Telmisartan Tablets IP", ["20mg", "40mg", "80mg"]),
    ("Levothyroxine Sodium Tablets IP", ["25mcg", "50mcg", "100mcg"]),
    ("Ibuprofen Tablets IP", ["200mg", "400mg"]),
    ("Ciprofloxacin Tablets IP", ["250mg", "500mg"]),
    ("Ondansetron Injection IP", ["2mg"]),
    ("Ceftriaxone for Injection IP", ["500mg", "1000mg"]),
    ("Dexamethasone Sodium Phosphate Injection IP", ["4mg"]),
    ("Ranitidine Tablets IP", ["150mg"]),
    ("Glimepiride Tablets IP", ["1mg", "2mg"]),
    ("Losartan Potassium Tablets IP", ["25mg", "50mg"]),
    ("Montelukast Sodium Tablets IP", ["10mg"]),
    ("Albendazole Tablets IP", ["400mg"]),
    ("Iron and Folic Acid Tablets IP", ["60mg"]),
    ("Calcium Carbonate and Vitamin D3 Tablets", ["500mg"]),
    ("Diclofenac Sodium Injection IP", ["25mg"]),
    ("Sodium Chloride Intravenous Infusion IP", ["0.9%"]),
    ("Dextrose Intravenous Infusion IP", ["5%"]),
    ("Cough Syrup (Dextromethorphan)", ["10mg"]),
    ("Vitamin B-Complex Syrup", ["5ml"]),
    ("Metronidazole Tablets IP", ["200mg", "400mg"]),
    ("Doxycycline Capsules IP", ["100mg"]),
    ("Hydrochlorothiazide Tablets IP", ["12.5mg", "25mg"]),
]

# Invented companies. Any resemblance to a real firm is unintended.
FICTIONAL_MAKERS = [
    ("Vireon Laboratories Ltd.", "Baddi, Himachal Pradesh"),
    ("Sunmark Pharmaceuticals Pvt. Ltd.", "Faridabad, Haryana"),
    ("Kavisha Remedies Ltd.", "Ahmedabad, Gujarat"),
    ("Orinet Healthcare Pvt. Ltd.", "Dehradun, Uttarakhand"),
    ("Pramana Drugs & Formulations", "Indore, Madhya Pradesh"),
    ("Lakshadhi Biotech Ltd.", "Hyderabad, Telangana"),
    ("Neelkanth Formulations Pvt. Ltd.", "Solan, Himachal Pradesh"),
    ("Astrella Life Sciences Ltd.", "Pune, Maharashtra"),
    ("Chandrika Pharma Works", "Nagpur, Maharashtra"),
    ("Hemant Bioceuticals Pvt. Ltd.", "Roorkee, Uttarakhand"),
    ("Trisara Labs Ltd.", "Vadodara, Gujarat"),
    ("Mayura Pharmaceuticals Ltd.", "Sikkim"),
    ("Godavari Medicare Pvt. Ltd.", "Visakhapatnam, Andhra Pradesh"),
    ("Anvaya Drugs Ltd.", "Chennai, Tamil Nadu"),
    ("Sibal Healthcare Pvt. Ltd.", "Jammu"),
]

LABS = [
    "CDL Kolkata",
    "CDTL Mumbai",
    "CDTL Chennai",
    "RDTL Guwahati",
    "RDTL Chandigarh",
    "State Drug Testing Laboratory, Lucknow",
    "State Drug Testing Laboratory, Bengaluru",
]

# Failure reasons phrased the way CDSCO tables phrase them.
REASONS = [
    ("Does not comply with IP for Dissolution", "DISSOLUTION"),
    ("Does not comply with IP for Assay", "ASSAY"),
    ("Assay of active ingredient found to be {pct}% of labelled amount", "ASSAY"),
    ("Does not comply with IP test for Description", "DESCRIPTION"),
    ("Does not comply with IP for Uniformity of Weight", "DESCRIPTION"),
    ("Does not comply with IP for Disintegration", "DISSOLUTION"),
    ("Does not comply with IP test for Sterility", "STERILITY"),
    ("Does not comply with IP for Bacterial Endotoxins", "ENDOTOXIN"),
    ("Does not comply with IP for Microbial Contamination", "MICROBIAL"),
    ("Does not comply with IP for Particulate Matter", "PARTICULATE"),
    ("Does not comply with IP for pH", "PH"),
    ("Does not comply with IP for Identification", "IDENTIFICATION"),
    ("Product declared Spurious - not manufactured by the labelled firm", "SPURIOUS"),
    ("Does not comply with IP for Clarity of Solution", "PARTICULATE"),
    ("Does not comply with IP for Related Substances", "CONTAMINANT"),
]

BATCH_SHAPES = [
    lambda r: f"{r.choice('ABKMPSTV')}{r.choice('ABCDGHJKLMNPRSTV')}{r.randint(1000, 9999)}{r.choice('ABCEHJKLMPRSTVWX')}",
    lambda r: f"{r.choice('ABKMPSTV')}{r.randint(10, 99)}{r.choice('ABCDGHJKLMNPRSTV')}{r.randint(100, 999)}",
    lambda r: f"{r.randint(100000, 999999)}",
    lambda r: f"{r.choice('ABKMPSTV')}{r.choice('ABCDGHJKLMNPRSTV')}{r.choice('ABCDGHJKLMNPRSTV')}{r.randint(100, 999)}",
    lambda r: f"T{r.randint(2224, 2612)}{r.choice('ABCDEFGH')}",
    lambda r: f"{r.choice(('BN', 'LT', 'MF'))}{r.randint(10000, 99999)}",
]


def month_range(end_year: int, end_month: int, count: int) -> list[str]:
    out = []
    y, m = end_year, end_month
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def build(rows_per_month: int, months: int, seed: int, end: str) -> list[dict]:
    r = random.Random(seed)
    end_year, end_month = (int(x) for x in end.split("-"))
    out: list[dict] = []
    seen_batches: set[str] = set()

    for alert_month in month_range(end_year, end_month, months):
        n = max(20, int(r.gauss(rows_per_month, rows_per_month * 0.18)))
        for _ in range(n):
            product, strengths = r.choice(PRODUCTS)
            strength = r.choice(strengths)
            maker, city = r.choice(FICTIONAL_MAKERS)

            for _ in range(6):
                batch = BATCH_SHAPES[r.randrange(len(BATCH_SHAPES))](r)
                if batch not in seen_batches:
                    break
            seen_batches.add(batch)

            reason_tpl, cls = r.choice(REASONS)
            reason = reason_tpl.format(pct=round(r.uniform(72.0, 91.5), 1))

            ay, am = (int(x) for x in alert_month.split("-"))
            # Manufactured 6-30 months before the alert; 24-36 month shelf life.
            back = r.randint(6, 30)
            my, mm = divmod((ay * 12 + am - 1) - back, 12)
            shelf = r.choice([24, 24, 36, 36, 18])
            ey, em = divmod((my * 12 + mm) + shelf, 12)

            out.append(
                canonical_row(
                    {
                        "drug_name": f"{product} {strength}",
                        "manufacturer_raw": f"M/s {maker}, {city}",
                        "batch_raw": batch,
                        "mfg_date": f"{my:04d}-{mm + 1:02d}",
                        "exp_date": f"{ey:04d}-{em + 1:02d}",
                        "failure_reason": reason,
                        "failure_class": cls,
                        "lab": r.choice(LABS),
                        "alert_month": alert_month,
                        "source_url": f"https://cdsco.gov.in/opencms/opencms/en/Drugs/Drug-Alerts/#sample-{alert_month}",
                        "synthetic": True,
                    }
                )
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "data" / "nsq_seed.jsonl"))
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--rows-per-month", type=int, default=135)
    ap.add_argument("--end", default="2026-08", help="most recent alert month, YYYY-MM")
    ap.add_argument("--seed", type=int, default=20260918)
    args = ap.parse_args()

    rows = build(args.rows_per_month, args.months, args.seed, args.end)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    months = sorted({r["alert_month"] for r in rows})
    print(f"wrote {len(rows)} synthetic NSQ rows -> {out}")
    print(f"alert months: {months[0]} .. {months[-1]} ({len(months)})")
    print(f"distinct batch skeletons: {len({r['batch_skeleton'] for r in rows})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
