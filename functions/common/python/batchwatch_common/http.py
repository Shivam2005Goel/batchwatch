"""API Gateway HTTP API plumbing: parsing in, JSON out, identity in between.

Handlers written against these helpers run unchanged under `sam local`, under
a deployed HTTP API, and under scripts/serve_local.py.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from decimal import Decimal
from typing import Any, Callable

CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.environ.get("BW_CORS_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "content-type,authorization,x-admin-key,x-device-id",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
}


class HttpError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        if isinstance(o, bytes):
            return base64.b64encode(o).decode("ascii")
        return super().default(o)


def response(status: int, body: Any, extra_headers: dict | None = None) -> dict:
    headers = {"content-type": "application/json", **CORS_HEADERS}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(body, cls=_Encoder, ensure_ascii=False),
    }


def ok(body: Any) -> dict:
    return response(200, body)


def created(body: Any) -> dict:
    return response(201, body)


def error(status: int, message: str, **extra) -> dict:
    return response(status, {"error": message, **extra})


def parse_body(event: dict) -> dict:
    raw = event.get("body") or ""
    if not raw:
        return {}
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise HttpError(400, f"body is not valid base64 utf-8: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HttpError(400, f"body is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise HttpError(400, "body must be a JSON object")
    return parsed


def query_params(event: dict) -> dict:
    return event.get("queryStringParameters") or {}


def path_params(event: dict) -> dict:
    return event.get("pathParameters") or {}


def headers_of(event: dict) -> dict:
    return {k.lower(): v for k, v in (event.get("headers") or {}).items()}


def method_of(event: dict) -> str:
    ctx = event.get("requestContext") or {}
    return (ctx.get("http") or {}).get("method") or event.get("httpMethod") or "GET"


def user_sub(event: dict, required: bool = True) -> str:
    """Identify the caller.

    Preference order:
      1. The Cognito JWT claim injected by the HTTP API authorizer (trusted).
      2. An X-Device-Id header (anonymous shelves, and the documented descope
         path if Cognito gets cut).

    The device id is explicitly NOT a security boundary - it is a namespace.
    Anything sensitive must sit behind the JWT authorizer, which is why
    BW_ALLOW_DEVICE_ID defaults to off outside local development.
    """
    ctx = event.get("requestContext") or {}
    authorizer = ctx.get("authorizer") or {}
    claims = (authorizer.get("jwt") or {}).get("claims") or authorizer.get("claims") or {}
    sub = claims.get("sub") or claims.get("username")
    if sub:
        return f"u_{sub}"

    if os.environ.get("BW_ALLOW_DEVICE_ID", "1") == "1":
        device = headers_of(event).get("x-device-id", "").strip()
        if device:
            safe = "".join(c for c in device if c.isalnum() or c in "-_")[:64]
            if safe:
                return f"d_{safe}"

    if required:
        raise HttpError(401, "sign in, or send an X-Device-Id header")
    return ""


def require_admin(event: dict) -> None:
    expected = os.environ.get("BW_ADMIN_KEY", "")
    if not expected:
        raise HttpError(503, "admin endpoint is disabled (BW_ADMIN_KEY not set)")
    if headers_of(event).get("x-admin-key", "") != expected:
        raise HttpError(403, "bad admin key")


def handler(fn: Callable[[dict, Any], dict]) -> Callable[[dict, Any], dict]:
    """Wrap a Lambda handler: CORS preflight, HttpError mapping, crash safety."""

    def wrapped(event: dict, context: Any = None) -> dict:
        if method_of(event) == "OPTIONS":
            return response(204, "")
        try:
            return fn(event, context)
        except HttpError as exc:
            return error(exc.status, exc.message, **exc.extra)
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace to a phone
            import traceback

            print("UNHANDLED", traceback.format_exc())
            return error(500, f"{type(exc).__name__}: {exc}")

    return wrapped
