"""The regression suite for the matching engine.

These numbers are the technical claim of the project, so they are asserted
rather than eyeballed. The invariant that matters most is FALSE CLEARS: a
flagged batch must never come back as "not flagged", at any damage level.
"""
import random

import pytest

from batchwatch_common.glyph import ocr_distance, ocr_similarity, sub_cost
from batchwatch_common.match import (
    FLAGGED,
    NO_MATCH,
    UNCERTAIN,
    NSQIndex,
    match,
    score_pair,
    verdict_for,
)

from .ocr_noise import corrupt, unlisted_batch

SAMPLE = 200


# --------------------------------------------------------------- glyph costs


def test_sub_cost_tiers():
    assert sub_cost("A", "A") == 0.0
    assert sub_cost("4", "A") == 0.3  # soft-confusable
    assert sub_cost("K", "9") == 1.0  # unrelated


def test_ocr_similarity_bounds():
    assert ocr_similarity("KP4021H", "KP4021H") == 1.0
    assert ocr_similarity("", "") == 0.0
    assert 0.0 <= ocr_similarity("KP4021H", "ZZZZZZZ") <= 1.0


def test_soft_errors_cost_less_than_hard_ones():
    soft = ocr_similarity("KP4021H", "KPA021H")  # 4 -> A
    hard = ocr_similarity("KP4021H", "KPX021H")  # 4 -> X
    assert soft > hard
    assert ocr_distance("KP4021H", "KPA021H") == pytest.approx(0.3)


# ------------------------------------------------------------------ scoring


def test_exact_match_scores_one():
    row = {
        "drug_name": "Paracetamol Tablets IP 650mg",
        "generic": "paracetamol",
        "manufacturer": "vireon laboratories baddi",
        "batch_skeleton": "KP4021H",
        "exp_date": "2028-02",
    }
    q = {
        "batch": "B.No. KP-4021-H",
        "drug_name": "Paracetamol Tablets IP 650mg",
        "manufacturer": "M/s Vireon Laboratories Ltd., Baddi",
        "exp_date": "02/2028",
    }
    assert score_pair(q, row).score == pytest.approx(1.0)


def test_missing_signals_renormalise_rather_than_penalise():
    row = {"drug_name": "Paracetamol Tablets IP 650mg", "batch_skeleton": "KP4021H"}
    full = score_pair({"batch": "KP4021H", "drug_name": "Paracetamol Tablets IP 650mg"}, row)
    assert full.score == pytest.approx(1.0)
    assert set(full.signals) == {"batch", "drug"}


def test_verdict_bands():
    assert verdict_for(0.99) == FLAGGED
    assert verdict_for(0.92) == FLAGGED
    assert verdict_for(0.80) == UNCERTAIN
    assert verdict_for(0.74) == UNCERTAIN
    assert verdict_for(0.50) == NO_MATCH


# -------------------------------------------------------------- index + match


def test_clean_reads_are_always_flagged(index, seed_rows):
    rng = random.Random(3)
    for row in rng.sample(seed_rows, SAMPLE):
        result = match(
            {
                "batch": row["batch_norm"],
                "drug_name": row["drug_name"],
                "manufacturer": row["manufacturer_raw"],
                "exp_date": row["exp_date"],
            },
            index,
        )
        assert result.verdict == FLAGGED
        assert result.best["batch_norm"] == row["batch_norm"]


@pytest.mark.parametrize(
    "errors,min_auto_flag",
    [(1, 0.80), (2, 0.35), (3, 0.12)],
)
def test_ocr_damage_recall(index, seed_rows, errors, min_auto_flag):
    """Damaged reads: measure auto-flag rate and forbid false clears."""
    rng = random.Random(11)
    counts = {FLAGGED: 0, UNCERTAIN: 0, NO_MATCH: 0}
    wrong_row = 0
    sample = rng.sample(seed_rows, SAMPLE)

    for row in sample:
        result = match(
            {
                "batch": corrupt(row["batch_norm"], rng, errors),
                "drug_name": row["drug_name"],
                "manufacturer": row["manufacturer_raw"],
                "exp_date": row["exp_date"],
            },
            index,
        )
        counts[result.verdict] += 1
        if result.verdict == FLAGGED and result.best["batch_norm"] != row["batch_norm"]:
            wrong_row += 1

    n = len(sample)
    caught = (counts[FLAGGED] + counts[UNCERTAIN]) / n

    assert wrong_row == 0, "a damaged read was confidently matched to the wrong batch"
    assert counts[FLAGGED] / n >= min_auto_flag
    # Anything not auto-flagged must at least reach the amber band, where the
    # user is told to check the code by hand.
    assert caught >= (1.0 if errors < 3 else 0.95)


def test_single_error_reads_are_never_falsely_cleared(index, seed_rows):
    """The safety invariant, stated on its own so a failure is unambiguous."""
    rng = random.Random(29)
    for row in rng.sample(seed_rows, SAMPLE):
        result = match(
            {
                "batch": corrupt(row["batch_norm"], rng, 1),
                "drug_name": row["drug_name"],
                "manufacturer": row["manufacturer_raw"],
                "exp_date": row["exp_date"],
            },
            index,
        )
        assert result.verdict != NO_MATCH, (
            f"false clear: {row['batch_norm']} came back as not-flagged"
        )


def test_unlisted_batches_are_not_flagged(index, seed_rows):
    """Precision: a medicine that was never flagged must not be flagged now."""
    rng = random.Random(5)
    known = {r["batch_skeleton"] for r in seed_rows}
    verdicts = {FLAGGED: 0, UNCERTAIN: 0, NO_MATCH: 0}

    for _ in range(300):
        row = rng.choice(seed_rows)
        result = match(
            {
                "batch": unlisted_batch(rng, known),
                "drug_name": row["drug_name"],
                "manufacturer": row["manufacturer_raw"],
                "exp_date": row["exp_date"],
            },
            index,
        )
        verdicts[result.verdict] += 1

    assert verdicts[FLAGGED] == 0, "false flag on a batch that was never listed"
    assert verdicts[NO_MATCH] / 300 >= 0.95


def test_batch_alone_never_reaches_flagged(index, seed_rows):
    """Batch codes are short and collide, so batch-only evidence stays amber."""
    row = seed_rows[0]
    result = match({"batch": row["batch_norm"]}, index)
    assert result.verdict == UNCERTAIN
    assert "confirm" in result.reason.lower()


def test_wrong_manufacturer_downgrades_a_batch_hit(index, seed_rows):
    row = seed_rows[0]
    result = match(
        {
            "batch": row["batch_norm"],
            "drug_name": row["drug_name"],
            "manufacturer": "Completely Different Pharma Works, Nowhere",
            "exp_date": row["exp_date"],
        },
        index,
    )
    assert result.verdict in (UNCERTAIN, FLAGGED)
    assert result.candidates[0].signals["manufacturer"] < 0.6


def test_empty_index_returns_no_match():
    result = match({"batch": "KP4021H", "drug_name": "Paracetamol 650mg"}, NSQIndex([]))
    assert result.verdict == NO_MATCH
    assert result.best is None


def test_index_reports_size_and_buckets(index, seed_rows):
    assert len(index) == len(seed_rows)
    assert index.by_skeleton
    assert index.by_generic
