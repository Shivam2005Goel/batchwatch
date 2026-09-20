"""Handing large payloads between Step Functions states.

A state machine payload is capped at 256KB and a month of NSQ rows is bigger
than that, so the stages pass references rather than data. S3 when a bucket is
configured, files on disk otherwise, with the same two functions either way.
"""
from __future__ import annotations

import json
import os
import pathlib

BUCKET = os.environ.get("BW_RAW_BUCKET", "")


def _local_root() -> pathlib.Path:
    base = os.environ.get("BW_LOCAL_DIR") or str(
        pathlib.Path(__file__).resolve().parents[4] / ".local"
    )
    root = pathlib.Path(base) / "ingest"
    root.mkdir(parents=True, exist_ok=True)
    return root


def put_blob(run_id: str, name: str, obj) -> str:
    """Store a JSON-serialisable object, return a reference to it."""
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if BUCKET:
        import boto3

        key = f"runs/{run_id}/{name}.json"
        boto3.client("s3").put_object(
            Bucket=BUCKET, Key=key, Body=data, ContentType="application/json"
        )
        return f"s3://{BUCKET}/{key}"

    path = _local_root() / run_id
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"{name}.json"
    target.write_bytes(data)
    return target.as_uri()


def get_blob(ref: str):
    """Read back whatever put_blob wrote."""
    if ref.startswith("s3://"):
        import boto3

        bucket, _, key = ref[5:].partition("/")
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body.decode("utf-8"))

    if ref.startswith("file://"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(ref)
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and ":" in path[:4]:
            path = path[1:]
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

    return json.loads(pathlib.Path(ref).read_text(encoding="utf-8"))


def put_pdf(run_id: str, name: str, data: bytes) -> str:
    if BUCKET:
        import boto3

        key = f"cdsco/{run_id}/{name}"
        boto3.client("s3").put_object(
            Bucket=BUCKET, Key=key, Body=data, ContentType="application/pdf"
        )
        return f"s3://{BUCKET}/{key}"

    path = _local_root() / run_id
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    target.write_bytes(data)
    return target.as_uri()


def get_pdf(ref: str) -> bytes:
    if ref.startswith("s3://"):
        import boto3

        bucket, _, key = ref[5:].partition("/")
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()

    from urllib.parse import unquote, urlparse

    if ref.startswith("file://"):
        parsed = urlparse(ref)
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and ":" in path[:4]:
            path = path[1:]
    else:
        path = ref
    return pathlib.Path(path).read_bytes()
