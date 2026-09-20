"""The single-table access patterns, exercised through the local driver.

Every assertion here corresponds to one DynamoDB call the deployed system
makes. If an access pattern needs more than one query, the key design is wrong.
"""
from batchwatch_common.ids import row_hash, ulid
from batchwatch_common.repo import (
    add_alert,
    add_shelf_item,
    delete_shelf_item,
    doc_seen,
    get_job,
    list_alerts,
    list_shelf,
    mark_doc,
    nsq_for_skeleton,
    put_job,
    save_nsq_rows,
    shelves_holding,
)
from batchwatch_common.normalise import canonical_row

ROW = {
    "drug_name": "Paracetamol Tablets IP 650mg",
    "manufacturer_raw": "M/s Vireon Laboratories Ltd., Baddi",
    "batch_raw": "KP4021H",
    "exp_date": "2028-02",
    "failure_reason": "Does not comply with IP for Dissolution",
    "alert_month": "2026-07",
}


def test_ulids_sort_by_creation_time():
    ids = [ulid(now_ms=1_700_000_000_000 + i * 1000) for i in range(20)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 20
    assert all(len(i) == 26 for i in ids)


def test_row_hash_is_stable_and_specific():
    a = canonical_row(ROW)
    b = canonical_row({**ROW, "batch_raw": "B.No. KP-4021-H"})  # same batch, printed differently
    c = canonical_row({**ROW, "batch_raw": "ZZ9999Q"})
    assert row_hash(a) == row_hash(b)
    assert row_hash(a) != row_hash(c)


def test_shelf_round_trip(tmp_store):
    item = add_shelf_item("d_alice", {"drug_name": "Paracetamol 650mg", "batch": "B.No. KP-4021-H"})
    assert item["batch_norm"] == "KP4021H"
    assert item["batch_skeleton"] == "KP4021H"

    items = list_shelf("d_alice")
    assert len(items) == 1
    assert items[0]["item_id"] == item["item_id"]
    assert items[0]["expired"] is False

    assert delete_shelf_item("d_alice", item["item_id"]) is True
    assert list_shelf("d_alice") == []
    assert delete_shelf_item("d_alice", item["item_id"]) is False


def test_shelves_are_isolated_per_user(tmp_store):
    add_shelf_item("d_alice", {"drug_name": "A", "batch": "KP4021H"})
    add_shelf_item("d_bob", {"drug_name": "B", "batch": "ZZ1234X"})
    assert len(list_shelf("d_alice")) == 1
    assert len(list_shelf("d_bob")) == 1
    assert list_shelf("d_alice")[0]["drug_name"] == "A"


def test_the_reverse_lookup(tmp_store):
    """One GSI1 query answers: whose shelf holds this batch?"""
    add_shelf_item("d_alice", {"drug_name": "Paracetamol 650mg", "batch": "KP4021H"})
    add_shelf_item("d_bob", {"drug_name": "Paracetamol 650mg", "batch": "B.No. KP-4021-H"})
    add_shelf_item("d_carol", {"drug_name": "Paracetamol 650mg", "batch": "ZZ9999Q"})

    holders = shelves_holding("KP4021H")
    owners = sorted(h["PK"] for h in holders)
    assert owners == ["USER#d_alice", "USER#d_bob"]


def test_nsq_rows_are_keyed_by_skeleton(tmp_store):
    assert save_nsq_rows([canonical_row(ROW)]) == 1
    rows = nsq_for_skeleton("KP4021H")
    assert len(rows) == 1
    assert rows[0]["drug_name"] == "Paracetamol Tablets IP 650mg"
    assert rows[0]["GSI1PK"] == "DRUG#paracetamol"


def test_saving_the_same_row_twice_does_not_duplicate_it(tmp_store):
    row = canonical_row(ROW)
    save_nsq_rows([row])
    save_nsq_rows([row])
    assert len(nsq_for_skeleton("KP4021H")) == 1


def test_alerts_come_back_newest_first(tmp_store):
    item = add_shelf_item("d_alice", {"drug_name": "Paracetamol 650mg", "batch": "KP4021H"})
    row = canonical_row(ROW)
    for _ in range(3):
        add_alert("d_alice", item, row, 0.98, "FLAGGED")
    alerts = list_alerts("d_alice")
    assert len(alerts) == 3
    assert [a["SK"] for a in alerts] == sorted((a["SK"] for a in alerts), reverse=True)
    assert alerts[0]["row_hash"] == row_hash(row)


def test_documents_are_recorded_by_url(tmp_store):
    url = "https://cdsco.gov.in/x/alert-july-2026.pdf"
    assert doc_seen(url) is False
    mark_doc(url, status="FETCHED", bytes=1234)
    assert doc_seen(url) is True
    assert doc_seen(url + "?v=2") is False


def test_pharmacy_jobs_round_trip_with_a_ttl(tmp_store):
    job_id = ulid()
    put_job({"job_id": job_id, "owner": "d_alice", "counts": {"FLAGGED": 1}, "results": []})
    fetched = get_job(job_id)
    assert fetched["owner"] == "d_alice"
    assert fetched["counts"]["FLAGGED"] == 1
    assert fetched["ttl"] > 0


def test_local_store_survives_a_restart(tmp_store, tmp_path, monkeypatch):
    add_shelf_item("d_alice", {"drug_name": "Paracetamol 650mg", "batch": "KP4021H"})

    from batchwatch_common import store as store_mod

    store_mod.reset_store()
    assert len(list_shelf("d_alice")) == 1
