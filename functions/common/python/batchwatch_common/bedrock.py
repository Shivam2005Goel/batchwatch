"""Claude on Amazon Bedrock: reading strips, mapping PDF rows, adjudicating.

Three jobs, each the kind of thing that is genuinely hard without a model:

  read_strip()     a photo of embossed foil -> labelled fields
  normalise_rows() a CDSCO table row with whatever headers that state used
                   this month -> the canonical schema
  adjudicate()     the 0.74-0.92 confidence band: is the code on this strip the
                   same code as one of these candidates?

Every entry point degrades instead of raising: if Bedrock is disabled, not
configured, or errors, the caller falls back to the deterministic path in
labelparse.py / the keyword classifier in schema.py. The app stays usable with
no model at all, which is also what makes it testable offline.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from .schema import FAILURE_CLASSES

# Read from the environment on every call rather than captured at import.
# Lambda sets these once at cold start so it costs nothing there, and it means
# status() cannot report a stale configuration - or a test cannot fail to turn
# the model off.


def model() -> str:
    """Bedrock model id. These carry an "anthropic." provider prefix."""
    return os.environ.get("BW_BEDROCK_MODEL", "anthropic.claude-opus-5")


def region() -> str:
    return os.environ.get("BW_BEDROCK_REGION") or os.environ.get("AWS_REGION") or "us-east-1"


def mode() -> str:
    """auto | on | off"""
    return os.environ.get("BW_BEDROCK", "auto").lower()

_client = None
_client_lock = threading.Lock()
_last_error = ""

# Circuit breaker. Constructing the client proves nothing - credentials are
# only resolved on the first real call - so a run of failures (no credentials,
# model access not granted, region wrong) has to stop us retrying. Without
# this, every scan pays the same timeout again before falling back.
_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = float(os.environ.get("BW_BEDROCK_COOLDOWN", "120"))
_consecutive_failures = 0
_open_until = 0.0


def _record_failure(message: str) -> None:
    global _consecutive_failures, _open_until, _last_error
    _last_error = message
    _consecutive_failures += 1
    if _consecutive_failures >= _FAILURE_THRESHOLD:
        _open_until = time.monotonic() + _COOLDOWN_SECONDS
        print(
            f"bedrock: {_consecutive_failures} consecutive failures, "
            f"backing off for {_COOLDOWN_SECONDS:.0f}s - {message}"
        )


def _record_success() -> None:
    global _consecutive_failures, _open_until, _last_error
    _consecutive_failures = 0
    _open_until = 0.0
    _last_error = ""


def _get_client():
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            from anthropic import AnthropicBedrockMantle

            _client = AnthropicBedrockMantle(aws_region=region())
    return _client


def available() -> bool:
    """True if a Bedrock call is worth attempting right now."""
    if mode() == "off":
        return False
    if _open_until and time.monotonic() < _open_until:
        return False
    try:
        _get_client()
        return True
    except Exception as exc:  # noqa: BLE001 - SDK missing entirely
        _record_failure(f"{type(exc).__name__}: {exc}")
        return False


def status() -> dict:
    """What /stats reports. Honest about a tripped breaker."""
    cooling = bool(_open_until and time.monotonic() < _open_until)
    return {
        "mode": mode(),
        "model": model(),
        "region": region(),
        "available": available(),
        "consecutive_failures": _consecutive_failures,
        "cooling_down": cooling,
        "error": _last_error,
    }


def reset() -> None:
    """Clear the breaker. Used by tests."""
    global _client
    with _client_lock:
        _client = None
    _record_success()


def _json_out(schema: dict) -> dict:
    return {"format": {"type": "json_schema", "schema": schema}}


def _first_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _call(
    messages: list,
    schema: dict,
    system: str,
    max_tokens: int = 2000,
    effort: str = "medium",
) -> dict | None:
    """One structured-output request. Returns None on any failure."""
    if not available():
        return None
    try:
        output_config: dict[str, Any] = _json_out(schema)
        output_config["effort"] = effort
        response = _get_client().messages.create(
            model=model(),
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config=output_config,
        )
        if getattr(response, "stop_reason", None) == "refusal":
            # A refusal is a deliberate answer, not a broken integration, so it
            # must not count toward the breaker.
            _record_success()
            _globals_set_error("model declined the request")
            return None
        text = _first_text(response)
        parsed = json.loads(text) if text else None
        _record_success()
        return parsed
    except Exception as exc:  # noqa: BLE001 - caller always has a fallback
        message = f"{type(exc).__name__}: {exc}"
        _record_failure(message)
        print(f"bedrock call failed: {message}")
        return None


def _globals_set_error(message: str) -> None:
    global _last_error
    _last_error = message


# ------------------------------------------------------------- read a strip

_STRIP_SCHEMA = {
    "type": "object",
    "properties": {
        "drug_name": {"type": "string", "description": "Product name with strength, as printed"},
        "manufacturer": {"type": "string", "description": "Manufacturer as printed, or empty"},
        "batch": {"type": "string", "description": "Batch/lot code only, no B.No. prefix"},
        "mfg_date": {"type": "string", "description": "Manufacture date as printed, or empty"},
        "exp_date": {"type": "string", "description": "Expiry date as printed, or empty"},
        "confidence": {"type": "number", "description": "0-1 confidence in the batch code"},
        "legible": {"type": "boolean"},
        "notes": {"type": "string", "description": "One short line on anything unclear"},
        "raw_text": {"type": "string", "description": "All text visible on the strip"},
    },
    "required": [
        "drug_name", "manufacturer", "batch", "mfg_date", "exp_date",
        "confidence", "legible", "notes", "raw_text",
    ],
    "additionalProperties": False,
}

_STRIP_SYSTEM = """You read photographs of Indian medicine strips and blister foil.

Report only what is printed. Never infer, complete or correct a batch code from
what would be plausible - a wrong batch code produces a wrong safety verdict
for a real person. If a character is ambiguous, say so in notes and lower the
confidence rather than guessing.

The batch code is the value after B.No., B/N, Batch No., LOT or similar. Return
the code alone, without the label. Indian strips print dates as MM/YYYY or
MON-YY; return them exactly as printed and let the caller parse them.
If the strip is unreadable, set legible false and leave fields empty."""


def read_strip(image_b64: str, media_type: str = "image/jpeg") -> dict | None:
    """Extract label fields from a photo. None if Bedrock is unavailable."""
    result = _call(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                    },
                    {"type": "text", "text": "Read this medicine strip."},
                ],
            }
        ],
        schema=_STRIP_SCHEMA,
        system=_STRIP_SYSTEM,
        # A dozen short fields: a small cap keeps the scan inside the latency
        # budget the demo is built around.
        max_tokens=1500,
        effort="low",
    )
    if result:
        result["source"] = "bedrock-vision"
    return result


# ----------------------------------------------------- normalise PDF rows

_ROWS_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "drug_name": {"type": "string"},
                    "manufacturer_raw": {"type": "string"},
                    "batch_raw": {"type": "string"},
                    "mfg_date": {"type": "string"},
                    "exp_date": {"type": "string"},
                    "failure_reason": {"type": "string"},
                    "failure_class": {"type": "string", "enum": list(FAILURE_CLASSES)},
                    "lab": {"type": "string"},
                    "usable": {
                        "type": "boolean",
                        "description": "False for header rows, footers and totals",
                    },
                },
                "required": [
                    "drug_name", "manufacturer_raw", "batch_raw", "mfg_date",
                    "exp_date", "failure_reason", "failure_class", "lab", "usable",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rows"],
    "additionalProperties": False,
}

_ROWS_SYSTEM = """You map rows from CDSCO Not-of-Standard-Quality drug alert
tables onto a fixed schema.

Column headings and column order change between months and between state
regulators, so work from the content of each cell rather than its position.
Return exactly one output row per input row, in the same order. Set usable
false for header rows, repeated column titles, page footers and totals; still
return an entry for them so the rows line up.

Copy values through as printed - do not reformat dates or expand
abbreviations. Leave a field empty when the row does not carry it. Choose the
failure_class that matches the stated reason for failure."""


def normalise_rows(raw_rows: list[list[str]], context: str = "") -> list[dict] | None:
    """Map raw table rows onto the canonical schema. None if unavailable."""
    if not raw_rows:
        return []
    payload = {
        "context": context,
        "rows": [[(cell or "").strip() for cell in row] for row in raw_rows],
    }
    result = _call(
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        schema=_ROWS_SCHEMA,
        system=_ROWS_SYSTEM,
        max_tokens=16000,
        effort="medium",
    )
    if result is None:
        return None
    return [row for row in result.get("rows", []) if row.get("usable", True)]


# ------------------------------------------------------------- adjudication

_ADJUDICATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["match", "no_match", "uncertain"]},
        "candidate_index": {
            "type": "integer",
            "description": "0-based index of the matching candidate, or -1",
        },
        "reason": {"type": "string", "description": "One sentence, plain language"},
    },
    "required": ["decision", "candidate_index", "reason"],
    "additionalProperties": False,
}

_ADJUDICATE_SYSTEM = """You settle borderline batch-code matches for a drug
recall checker.

You are given what was read from a medicine strip - and the photo itself when
one is available - plus a short list of batch codes that a regulator has
flagged. Decide whether the code on the strip is the same code as one of the
candidates, allowing for OCR confusions on embossed foil (0/O/D/Q, 1/I/L, 5/S,
8/B, 2/Z, 6/G, 4/A, 7/T).

Answer no_match when the codes plainly differ, even by one confident
character. Answer uncertain when you cannot tell - that is a useful answer
here, not a failure. Only answer match when you would be comfortable telling
someone their medicine was recalled. Give the reason in one plain sentence a
patient would understand, naming the characters you compared."""


def adjudicate(
    query: dict,
    candidates: list[dict],
    image_b64: str = "",
    media_type: str = "image/jpeg",
) -> dict | None:
    """Resolve a middle-band match. None if Bedrock is unavailable."""
    if not candidates:
        return None

    summary = {
        "read_from_strip": {
            "batch": query.get("batch", ""),
            "drug_name": query.get("drug_name", ""),
            "manufacturer": query.get("manufacturer", ""),
            "exp_date": query.get("exp_date", ""),
        },
        "candidates": [
            {
                "index": i,
                "batch": c.get("batch_norm") or c.get("batch_raw", ""),
                "drug_name": c.get("drug_name", ""),
                "manufacturer": c.get("manufacturer_raw", ""),
                "exp_date": c.get("exp_date", ""),
            }
            for i, c in enumerate(candidates[:5])
        ],
    }

    content: list[dict] = []
    if image_b64:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": image_b64},
            }
        )
    content.append({"type": "text", "text": json.dumps(summary, ensure_ascii=False)})

    return _call(
        messages=[{"role": "user", "content": content}],
        schema=_ADJUDICATE_SCHEMA,
        system=_ADJUDICATE_SYSTEM,
        max_tokens=1000,
        # Correctness matters more than latency for the one call that can
        # change a verdict.
        effort="high",
    )
