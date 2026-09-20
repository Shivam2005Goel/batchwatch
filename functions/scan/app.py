"""POST /scan - a photo (or typed label text) in, a verdict out.

Auth is optional here on purpose: making someone sign up before they can see
what the thing does costs more than the auth story gains.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import time

from batchwatch_common import bedrock
from batchwatch_common.http import HttpError, handler, ok, parse_body, user_sub
from batchwatch_common.labelparse import parse_label
from batchwatch_common.repo import load_index, now_iso
from batchwatch_common.store import get_store
from batchwatch_common.verdict import build_verdict

MAX_IMAGE_BYTES = int(os.environ.get("BW_MAX_IMAGE_BYTES", str(6 * 1024 * 1024)))
ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}
EXTRACT_TTL_SECONDS = 24 * 3600


def _cache_get(image_hash: str) -> dict | None:
    """Vision calls cost money; the same photo should only cost once."""
    item = get_store().get(f"SCAN#{image_hash}", "EXTRACT")
    if not item:
        return None
    try:
        return json.loads(item["fields"])
    except (KeyError, json.JSONDecodeError):
        return None


def _cache_put(image_hash: str, fields: dict) -> None:
    get_store().put(
        {
            "PK": f"SCAN#{image_hash}",
            "SK": "EXTRACT",
            "type": "SCAN_CACHE",
            # Only the extracted text is kept, never the image itself, and it
            # self-deletes after a day.
            "fields": json.dumps(fields, ensure_ascii=False),
            "cached_at": now_iso(),
            "ttl": int(time.time()) + EXTRACT_TTL_SECONDS,
        }
    )


def _extract(body: dict) -> dict:
    """Get label fields from whatever the client sent."""
    image_b64 = (body.get("image") or "").strip()
    media_type = (body.get("media_type") or "image/jpeg").lower()
    text = (body.get("text") or "").strip()

    if image_b64:
        if media_type not in ALLOWED_MEDIA:
            raise HttpError(400, f"unsupported media_type: {media_type}")
        if "," in image_b64[:64] and image_b64.lstrip().startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        try:
            raw = base64.b64decode(image_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HttpError(400, f"image is not valid base64: {exc}") from exc
        if len(raw) > MAX_IMAGE_BYTES:
            raise HttpError(
                413,
                f"image is {len(raw) // 1024}KB; resize to under "
                f"{MAX_IMAGE_BYTES // 1024}KB before uploading",
            )

        image_hash = hashlib.sha256(raw).hexdigest()[:32]
        cached = _cache_get(image_hash)
        if cached:
            cached["cached"] = True
            return cached

        fields = bedrock.read_strip(image_b64, media_type)
        if fields:
            fields["cached"] = False
            _cache_put(image_hash, fields)
            return fields

        if text:
            return parse_label(text)
        raise HttpError(
            503,
            "image reading is unavailable right now - type the label text "
            "instead and send it as 'text'",
            bedrock=bedrock.status(),
        )

    if text:
        return parse_label(text)

    raise HttpError(400, "send either 'image' (base64) or 'text' (the label as typed)")


@handler
def lambda_handler(event: dict, context=None) -> dict:
    body = parse_body(event)
    fields = _extract(body)

    query = {
        "batch": fields.get("batch") or "",
        "drug_name": fields.get("drug_name") or "",
        "manufacturer": fields.get("manufacturer") or "",
        "exp_date": fields.get("exp_date") or "",
    }

    if not query["batch"]:
        return ok(
            {
                "verdict": "UNREADABLE",
                "tone": "amber",
                "headline": "We could not find a batch number",
                "reason": fields.get("notes")
                or "No batch number was visible. Try again in better light, or type it in.",
                "extracted": fields,
                "match": None,
                "candidates": [],
                "disclaimer": _disclaimer(),
            }
        )

    index = load_index()
    result = build_verdict(
        query,
        index,
        image_b64=(body.get("image") or "") if body.get("adjudicate", True) else "",
        media_type=(body.get("media_type") or "image/jpeg").lower(),
        allow_adjudication=bool(body.get("adjudicate", True)),
    )
    result["extracted"] = fields
    result["corpus_rows"] = len(index)
    result["user"] = user_sub(event, required=False)
    return ok(result)


def _disclaimer() -> str:
    from batchwatch_common.verdict import DISCLAIMER

    return DISCLAIMER
