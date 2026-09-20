"""The no-model label reader.

It backs the "type it in instead" path and every deployment without Bedrock, so
it has to be right about the one field that matters: the batch code.
"""
import pytest

from batchwatch_common.labelparse import find_batch, find_dates, parse_label

STRIP = """PARACETAMOL TABLETS IP 650mg
B.No. KP4021H
MFG 03/2026   EXP 02/2028
Mfd. by: Vireon Laboratories Ltd., Baddi
MRP Rs. 24.50 incl. of all taxes"""


def test_reads_a_whole_strip():
    result = parse_label(STRIP)
    assert result["batch"] == "KP4021H"
    assert result["drug_name"] == "PARACETAMOL TABLETS IP 650mg"
    assert result["manufacturer"] == "Vireon Laboratories Ltd., Baddi"
    assert result["mfg_date"] == "2026-03"
    assert result["exp_date"] == "2028-02"
    assert result["legible"] is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("B.No. KP4021H", "KP4021H"),
        ("Batch No: AZ-9931-K", "AZ9931K"),
        ("B/N: T2451C EXP 09/27", "T2451C"),
        # The printer ran the fields together on one line.
        ("B.No. KP4021H MFG 03/2026 EXP 02/2028", "KP4021H"),
        # The code itself is printed with separators.
        ("B.No. KP 4021 H  MFG 03/2026", "KP4021H"),
        ("LOT NO. AX9931", "AX9931"),
    ],
)
def test_finds_the_batch_code(text, expected):
    assert find_batch(text) == expected


def test_finds_an_unlabelled_batch_code():
    assert find_batch("Amlodipine 5mg\nKP4021H\n03/2026 02/2028") == "KP4021H"


def test_does_not_mistake_a_price_or_a_date_for_a_batch():
    assert find_batch("MRP Rs. 24.50\n03/2026\n02/2028") == ""


def test_returns_nothing_rather_than_guessing():
    result = parse_label("Cough Syrup 100ml\nno batch printed here")
    assert result["batch"] == ""
    assert result["legible"] is False
    assert result["confidence"] < 0.3
    assert "No batch number" in result["notes"]


def test_labelled_dates_win():
    assert find_dates("MFG 03/2026   EXP 02/2028") == ("2026-03", "2028-02")


def test_two_unlabelled_dates_are_read_as_mfg_then_exp():
    assert find_dates("KP4021H\n03/2026 02/2028") == ("2026-03", "2028-02")


def test_a_single_unlabelled_date_does_not_fill_the_other_field():
    """Guessing an expiry wrong is worse than leaving it blank."""
    mfg, exp = find_dates("B/N T2451C EXP 09/27")
    assert exp == "2027-09"
    assert mfg == ""


def test_swapped_dates_are_put_back_in_order():
    assert find_dates("MFG 02/2028  EXP 03/2026") == ("2026-03", "2028-02")


def test_empty_input_is_safe():
    result = parse_label("")
    assert result["batch"] == ""
    assert result["confidence"] == 0.2
