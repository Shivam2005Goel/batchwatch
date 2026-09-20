"""Bedrock integration: it must degrade, never crash, and never lie about itself.

No live calls are made here. What is asserted is the contract every caller
depends on - that an unavailable model produces a clean fallback rather than a
500, and that a run of failures stops us paying the timeout on every request.
"""
from __future__ import annotations

import json

import pytest

from batchwatch_common import bedrock


@pytest.fixture(autouse=True)
def clean_breaker():
    bedrock.reset()
    yield
    bedrock.reset()


def test_mode_off_disables_everything(monkeypatch):
    monkeypatch.setenv("BW_BEDROCK", "off")
    assert bedrock.available() is False
    assert bedrock.read_strip("", "image/jpeg") is None
    assert bedrock.normalise_rows([["a", "b"]]) is None
    assert bedrock.adjudicate({}, [{"batch_norm": "KP4021H"}]) is None


def test_status_reports_the_model_and_region():
    status = bedrock.status()
    assert status["model"].startswith("anthropic."), "Bedrock ids carry the provider prefix"
    assert status["region"]
    assert set(status) >= {"mode", "model", "region", "available", "cooling_down", "error"}


def test_breaker_opens_after_repeated_failures(monkeypatch):
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError("Could not resolve AWS credentials from session")

    monkeypatch.setenv("BW_BEDROCK", "auto")
    monkeypatch.setattr(bedrock, "_get_client", boom)

    for _ in range(6):
        assert bedrock.read_strip("x", "image/jpeg") is None

    # Three failures trip it; the rest short-circuit without another attempt.
    assert calls["n"] == bedrock._FAILURE_THRESHOLD
    status = bedrock.status()
    assert status["available"] is False
    assert status["cooling_down"] is True
    assert "credentials" in status["error"]


def test_a_success_closes_the_breaker(monkeypatch):
    class FakeBlock:
        type = "text"
        text = json.dumps(
            {
                "drug_name": "Paracetamol Tablets IP 650mg",
                "manufacturer": "Vireon Laboratories Ltd",
                "batch": "KP4021H",
                "mfg_date": "03/2026",
                "exp_date": "02/2028",
                "confidence": 0.94,
                "legible": True,
                "notes": "",
                "raw_text": "PARACETAMOL ... B.No. KP4021H",
            }
        )

    class FakeResponse:
        content = [FakeBlock()]
        stop_reason = "end_turn"

    class FakeMessages:
        def create(self, **kwargs):
            # The request shape the whole integration depends on.
            assert kwargs["model"].startswith("anthropic.")
            assert kwargs["output_config"]["format"]["type"] == "json_schema"
            assert kwargs["output_config"]["format"]["schema"]["additionalProperties"] is False
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setenv("BW_BEDROCK", "auto")
    monkeypatch.setattr(bedrock, "_get_client", lambda: FakeClient())

    fields = bedrock.read_strip("x", "image/jpeg")
    assert fields is not None
    assert fields["batch"] == "KP4021H"
    assert fields["source"] == "bedrock-vision"
    assert bedrock.status()["consecutive_failures"] == 0


def test_a_refusal_is_not_a_failure(monkeypatch):
    class FakeResponse:
        content = []
        stop_reason = "refusal"

    class FakeClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**_kwargs):
                return FakeResponse()

    monkeypatch.setenv("BW_BEDROCK", "auto")
    monkeypatch.setattr(bedrock, "_get_client", lambda: FakeClient())

    assert bedrock.read_strip("x", "image/jpeg") is None
    # A refusal is an answer, not a broken integration, so the breaker stays shut.
    assert bedrock.status()["consecutive_failures"] == 0
    assert "declined" in bedrock.status()["error"]


def test_normalise_rows_filters_unusable_rows(monkeypatch):
    class FakeBlock:
        type = "text"
        text = json.dumps(
            {
                "rows": [
                    {
                        "drug_name": "S.No.", "manufacturer_raw": "", "batch_raw": "",
                        "mfg_date": "", "exp_date": "", "failure_reason": "",
                        "failure_class": "OTHER", "lab": "", "usable": False,
                    },
                    {
                        "drug_name": "Paracetamol Tablets IP 650mg",
                        "manufacturer_raw": "M/s Vireon Laboratories Ltd",
                        "batch_raw": "KP4021H", "mfg_date": "03/2026", "exp_date": "02/2028",
                        "failure_reason": "Dissolution", "failure_class": "DISSOLUTION",
                        "lab": "CDL Kolkata", "usable": True,
                    },
                ]
            }
        )

    class FakeResponse:
        content = [FakeBlock()]
        stop_reason = "end_turn"

    class FakeClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**_kwargs):
                return FakeResponse()

    monkeypatch.setenv("BW_BEDROCK", "auto")
    monkeypatch.setattr(bedrock, "_get_client", lambda: FakeClient())

    rows = bedrock.normalise_rows([["S.No.", "Name"], ["1", "Paracetamol"]])
    assert len(rows) == 1
    assert rows[0]["batch_raw"] == "KP4021H"


def test_normalise_rows_on_empty_input_is_empty_not_none():
    assert bedrock.normalise_rows([]) == []


def test_adjudicate_needs_candidates():
    assert bedrock.adjudicate({"batch": "KP4021H"}, []) is None
