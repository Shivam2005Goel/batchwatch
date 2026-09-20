"""Ingest pipeline: header detection, column mapping, canonicalisation, fan-out."""
from __future__ import annotations

import pytest

from batchwatch_common.cdsco import find_pdf_links, guess_alert_month
from batchwatch_common.ingest import (
    fanout,
    find_header,
    ingest_rows,
    normalise_heuristic,
    to_canonical,
)
from batchwatch_common.normalise import canonical_row

# A CDSCO alert table as pdfplumber hands it over: a title row, a header row,
# then the data, with a footer that must not become a medicine.
CDSCO_TABLE = [
    ["DRUGS DECLARED AS NOT OF STANDARD QUALITY FOR THE MONTH OF JULY 2026", "", "", "", "", "", ""],
    ["S.No.", "Name of Drug", "Batch No.", "Mfg. Date", "Exp. Date",
     "Name and address of Manufacturer", "Reason for failure"],
    ["1", "Paracetamol Tablets IP 650mg", "KP4021H", "03/2026", "02/2028",
     "M/s Vireon Laboratories Ltd., Baddi", "Does not comply with IP for Dissolution"],
    ["2", "Azithromycin Tablets IP 500mg", "AZ-9931-K", "11/2025", "10/2027",
     "M/s Trisara Labs Ltd., Vadodara", "Does not comply with IP test for Sterility"],
    ["3", "Amlodipine Tablets IP 5mg", "B.No. T2451C", "JAN 2026", "DEC 2027",
     "M/s Kavisha Remedies Ltd., Ahmedabad", "Assay found to be 82.4% of labelled amount"],
    ["", "Total: 3", "", "", "", "", ""],
]


def test_find_header_skips_the_title_row():
    idx, mapping = find_header(CDSCO_TABLE)
    assert idx == 1
    assert set(mapping.values()) >= {
        "drug_name", "batch_raw", "mfg_date", "exp_date", "manufacturer", "failure_reason"
    }


def test_find_header_gives_up_on_a_table_with_no_header():
    idx, mapping = find_header([["a", "b"], ["c", "d"]])
    assert idx == -1
    assert mapping == {}


def test_heuristic_mapping_reads_the_data_rows():
    mapped = normalise_heuristic(CDSCO_TABLE, context="test")
    assert len(mapped) == 3
    first = mapped[0]
    assert first["drug_name"] == "Paracetamol Tablets IP 650mg"
    assert first["batch_raw"] == "KP4021H"
    assert first["manufacturer_raw"] == "M/s Vireon Laboratories Ltd., Baddi"
    assert first["failure_class"] == "DISSOLUTION"


def test_heuristic_mapping_drops_the_totals_footer():
    mapped = normalise_heuristic(CDSCO_TABLE, context="test")
    assert all("Total" not in (m.get("drug_name") or "") for m in mapped)


def test_to_canonical_produces_matchable_rows():
    rows = to_canonical(
        normalise_heuristic(CDSCO_TABLE), alert_month="2026-07", source_url="https://example.test/x"
    )
    assert len(rows) == 3
    by_batch = {r["batch_norm"]: r for r in rows}
    assert set(by_batch) == {"KP4021H", "AZ9931K", "T2451C"}
    assert by_batch["AZ9931K"]["severity"] == "CRITICAL"  # sterility
    assert by_batch["T2451C"]["severity"] == "HIGH"       # assay
    assert by_batch["T2451C"]["mfg_date"] == "2026-01"
    assert all(r["alert_month"] == "2026-07" for r in rows)


def test_to_canonical_drops_rows_without_a_batch():
    rows = to_canonical([{"drug_name": "Something", "batch_raw": ""}], alert_month="2026-07")
    assert rows == []


# ------------------------------------------------------------------- fanout


def _row(batch: str, drug: str = "Paracetamol Tablets IP 650mg") -> dict:
    return canonical_row(
        {
            "drug_name": drug,
            "manufacturer_raw": "M/s Vireon Laboratories Ltd., Baddi",
            "batch_raw": batch,
            "exp_date": "2028-02",
            "failure_reason": "Does not comply with IP for Dissolution",
            "alert_month": "2026-07",
        }
    )


def test_fanout_finds_the_shelf_holding_the_batch(tmp_store):
    from batchwatch_common.repo import add_shelf_item, list_alerts

    add_shelf_item(
        "d_alice",
        {
            "drug_name": "Paracetamol Tablets IP 650mg",
            "batch": "KP4021H",
            "manufacturer": "M/s Vireon Laboratories Ltd., Baddi",
            "exp_date": "2028-02",
        },
    )
    add_shelf_item("d_bob", {"drug_name": "Paracetamol Tablets IP 650mg", "batch": "ZZ9999Q"})

    result = fanout([_row("KP4021H")], deep=False, notify=False)
    assert result["alerts_created"] == 1
    assert len(list_alerts("d_alice")) == 1
    assert len(list_alerts("d_bob")) == 0


def test_fanout_is_idempotent(tmp_store):
    from batchwatch_common.repo import add_shelf_item, list_alerts

    add_shelf_item("d_alice", {"drug_name": "Paracetamol Tablets IP 650mg", "batch": "KP4021H"})
    rows = [_row("KP4021H")]
    assert fanout(rows, deep=False, notify=False)["alerts_created"] == 1
    assert fanout(rows, deep=False, notify=False)["alerts_created"] == 0
    assert len(list_alerts("d_alice")) == 1


def test_deep_fanout_catches_a_mis_read_batch_on_the_shelf(tmp_store):
    """A shelf entry saved from a slightly wrong OCR read still gets the alert.

    The exact GSI lookup cannot find it - the skeletons differ - which is
    precisely why the deep sweep exists.
    """
    from batchwatch_common.normalise import skeleton
    from batchwatch_common.repo import add_shelf_item, list_alerts

    add_shelf_item(
        "d_carol",
        {
            "drug_name": "Paracetamol Tablets IP 650mg",
            "batch": "KPA021H",  # 4 misread as A
            "manufacturer": "M/s Vireon Laboratories Ltd., Baddi",
            "exp_date": "2028-02",
        },
    )
    row = _row("KP4021H")
    assert skeleton("KPA021H") != row["batch_skeleton"]

    assert fanout([row], deep=False, notify=False)["alerts_created"] == 0
    assert fanout([row], deep=True, notify=False)["alerts_created"] == 1
    assert len(list_alerts("d_carol")) == 1


def test_a_warm_reader_picks_up_a_corpus_change_from_another_process(tmp_store):
    """The read path and the ingest path are separate Lambdas in production.

    Clearing the in-process cache is not enough: a warm read function would keep
    answering from a stale index, so the shelf would still show a just-flagged
    medicine as clear. The shared corpus version in the table is what fixes it,
    and this test deliberately never calls invalidate_index() or force=True.
    """
    from batchwatch_common import repo

    # The "read path" warms its index.
    repo.save_nsq_rows([_row("AA1111A")])
    warm = repo.load_index()
    assert len(warm) == 1

    # The "ingest path", conceptually another process, writes and publishes.
    repo.save_nsq_rows([_row("BB2222B")])
    repo.bump_corpus_version()

    # The read path must notice on its next request.
    refreshed = repo.load_index()
    assert len(refreshed) == 2
    assert {r["batch_norm"] for r in refreshed.rows} == {"AA1111A", "BB2222B"}


def test_a_warm_reader_does_not_rebuild_when_nothing_changed(tmp_store):
    from batchwatch_common import repo

    repo.save_nsq_rows([_row("AA1111A")])
    repo.bump_corpus_version()
    first = repo.load_index()
    second = repo.load_index()
    assert first is second, "the index was rebuilt when the corpus had not moved"


def test_ingest_rows_publishes_a_new_corpus_version(tmp_store):
    from batchwatch_common import repo

    repo.save_nsq_rows([_row("AA1111A")])
    before = repo.corpus_version()
    result = ingest_rows([_row("CC3333C")], deep=False, notify=False)
    assert result["corpus_version"] != before
    assert repo.corpus_version() == result["corpus_version"]


def test_ingest_rows_saves_and_fans_out(tmp_store):
    from batchwatch_common.repo import add_shelf_item, load_index

    add_shelf_item("d_dave", {"drug_name": "Paracetamol Tablets IP 650mg", "batch": "KP4021H"})
    result = ingest_rows([_row("KP4021H"), _row("QQ1234X")], deep=False, notify=False)
    assert result["rows_saved"] == 2
    assert result["alerts_created"] == 1
    assert len(load_index(force=True)) == 2


# ------------------------------------------------------------------- cdsco


def test_guess_alert_month():
    assert guess_alert_month("Drug Alert for the month of July 2026") == "2026-07"
    assert guess_alert_month("nsq-alert-2026-03.pdf") == "2026-03"
    assert guess_alert_month("SEPTEMBER, 2025") == "2025-09"
    assert guess_alert_month("no month here") == ""


def test_find_pdf_links_keeps_alerts_and_drops_the_rest():
    html = """
    <ul>
      <li><a href="/pdf-documents/alerts/Drug-Alert-July-2026.pdf">Drug Alert July 2026</a></li>
      <li><a href="/pdf-documents/forms/Form-45.pdf">Application Form 45</a></li>
      <li><a href="https://cdsco.gov.in/x/NSQ-March-2026.pdf">NSQ list March 2026</a></li>
    </ul>
    """
    links = find_pdf_links(html, "https://cdsco.gov.in/opencms/en/Drugs/Drug-Alerts/")
    urls = [link["url"] for link in links]
    assert any("Drug-Alert-July-2026" in u for u in urls)
    assert any("NSQ-March-2026" in u for u in urls)
    assert not any("Form-45" in u for u in urls)
    assert links[0]["alert_month"] in ("2026-07", "2026-03")


def test_find_pdf_links_resolves_relative_urls():
    links = find_pdf_links(
        '<a href="../x/alert-jan-2026.pdf">Alert</a>',
        "https://cdsco.gov.in/opencms/en/Drugs/Drug-Alerts/",
    )
    assert links[0]["url"].startswith("https://cdsco.gov.in/")
    assert ".." not in links[0]["url"]


@pytest.mark.parametrize("html", ["", "<html><body>nothing</body></html>"])
def test_find_pdf_links_handles_empty_pages(html):
    assert find_pdf_links(html, "https://cdsco.gov.in/") == []
