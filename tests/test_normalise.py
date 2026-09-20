import pytest

from batchwatch_common.normalise import (
    batch_keys,
    canonical_row,
    drug_key,
    is_expired,
    month_delta,
    norm_batch,
    norm_generic,
    norm_manufacturer,
    parse_month,
    parse_strength,
    plausible_batch,
    row_is_usable,
    skeleton,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("KP4021H", "KP4021H"),
        ("B.No. KP-4021-H", "KP4021H"),
        ("b.no.kp4021h", "KP4021H"),
        ("Batch No: KP 4021 H", "KP4021H"),
        ("Batch Number 4471X", "4471X"),
        ("B/N 7781A", "7781A"),
        ("LOT NO. AX9931", "AX9931"),
        ("  kp4021h  ", "KP4021H"),
        ("", ""),
        (None, ""),
    ],
)
def test_norm_batch_strips_labels(raw, expected):
    assert norm_batch(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # OCR splits or hyphenates the label word; the collapsed-form pass catches it.
        ("BA TCH NO: A0D629", "A0D629"),
        ("BATC-H NO: RNM434", "RNM434"),
        ("B ATCH NO: TN45456", "TN45456"),
        ("B.N-o. T8A692", "T8A692"),
        ("L-OT A6N19", "A6N19"),
    ],
)
def test_norm_batch_survives_split_label_words(raw, expected):
    assert norm_batch(raw) == expected


@pytest.mark.parametrize("code", ["BN12345", "LT56667", "MF12345", "BNX449"])
def test_norm_batch_keeps_codes_that_look_like_labels(code):
    """BN/LT are real batch prefixes. Stripping them would corrupt live codes."""
    assert norm_batch(code) == code


def test_norm_batch_never_strips_everything():
    assert norm_batch("BATCH") == "BATCH"


def test_skeleton_collapses_confusables():
    assert skeleton("SDO1B42") == "5001842"
    assert skeleton("KP4021H") == "KP4021H"
    assert skeleton("B.No. IO5G") == "1056"


def test_skeleton_is_stable_across_label_formats():
    """The scan path and the ingest path must agree or the reverse lookup dies."""
    printed = "B.No. KP-4021-H"
    from_pdf = "KP4021H"
    assert skeleton(printed) == skeleton(from_pdf)
    assert batch_keys(printed) == batch_keys(from_pdf)


@pytest.mark.parametrize(
    "code,ok",
    [("KP4021H", True), ("12345", True), ("AB", False), ("ABCDEF", False), ("", False),
     ("A" * 21 + "1", False)],
)
def test_plausible_batch(code, ok):
    assert plausible_batch(code) is ok


def test_norm_manufacturer_drops_legal_noise():
    assert norm_manufacturer("M/s Nestor Pharmaceuticals Ltd., Faridabad") == (
        "nestor pharmaceuticals faridabad"
    )
    assert norm_manufacturer("VIREON LABORATORIES PVT. LTD.") == "vireon laboratories"


def test_norm_generic_and_strength():
    assert norm_generic("Paracetamol Tablets IP 650mg") == "paracetamol"
    assert parse_strength("Paracetamol Tablets IP 650mg") == "650mg"
    assert drug_key("Paracetamol Tablets IP 650mg") == "paracetamol 650mg"
    assert parse_strength("Amoxycillin 500mg + Clavulanic Acid 125 mg") == "500mg+125mg"
    assert parse_strength("Amlodipine 2.50mg") == "2.5mg"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("03/2026", "2026-03"),
        ("MAR 2026", "2026-03"),
        ("MARCH-26", "2026-03"),
        ("SEPT 26", "2026-09"),
        ("03-26", "2026-03"),
        ("2028-02", "2028-02"),
        ("15/03/2026", "2026-03"),
        ("032026", "2026-03"),
        ("EXP. 02/2028", "2028-02"),
        ("MFG 03/2026", "2026-03"),
        ("no date here", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_parse_month(raw, expected):
    assert parse_month(raw) == expected


def test_month_delta_and_expiry():
    assert month_delta("2028-02", "2028-03") == 1
    assert month_delta("2028-02", "2029-02") == 12
    assert month_delta("2028-02", "") is None
    import datetime

    today = datetime.date(2026, 9, 18)
    assert is_expired("2026-08", today) is True
    assert is_expired("2026-09", today) is False
    assert is_expired("", today) is False


def test_canonical_row_fills_derived_fields():
    row = canonical_row(
        {
            "drug_name": "Paracetamol Tablets IP 650mg",
            "manufacturer_raw": "M/s Vireon Laboratories Ltd., Baddi",
            "batch_raw": "B.No. KP-4021-H",
            "mfg_date": "03/2026",
            "exp_date": "02/2028",
            "failure_reason": "Does not comply with IP for Dissolution",
            "alert_month": "2026-07",
        }
    )
    assert row["batch_norm"] == "KP4021H"
    assert row["batch_skeleton"] == "KP4021H"
    assert row["generic"] == "paracetamol"
    assert row["strength"] == "650mg"
    assert row["manufacturer"] == "vireon laboratories baddi"
    assert row["mfg_date"] == "2026-03"
    assert row["exp_date"] == "2028-02"
    assert row["failure_class"] == "DISSOLUTION"
    assert row["severity"] == "HIGH"
    assert row_is_usable(row)


def test_canonical_row_is_idempotent():
    once = canonical_row(
        {
            "drug_name": "Azithromycin Tablets IP 500mg",
            "manufacturer_raw": "M/s Trisara Labs Ltd., Vadodara",
            "batch_raw": "AZ-9931-K",
            "exp_date": "11/2027",
            "failure_reason": "Sterility failure",
            "alert_month": "2026-05",
        }
    )
    twice = canonical_row(once)
    assert once == twice


def test_canonical_row_rejects_unusable():
    row = canonical_row({"drug_name": "", "batch_raw": "AB"})
    assert not row_is_usable(row)
