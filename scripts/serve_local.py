"""Run the whole API on a laptop, with no AWS account.

This is not a mock. It builds real API Gateway HTTP API v2 events and calls the
real Lambda handlers, which talk to the real repo layer over the LocalStore
driver. If it works here it works deployed, and that is the point: the only
difference is which Store implementation get_store() picks.

    python scripts/load_seed.py
    python scripts/serve_local.py

Then open http://127.0.0.1:8000 (the built web app, if you have run
`npm run build` in web/) or call the API directly.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import pathlib
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functions" / "common" / "python"))
for name in ("scan", "shelf", "search", "pharmacy", "admin"):
    sys.path.insert(0, str(ROOT / "functions" / name))

os.environ.setdefault("BW_STORE", "local")
os.environ.setdefault("BW_LOCAL_DIR", str(ROOT / ".local"))
os.environ.setdefault("BW_ALLOW_DEVICE_ID", "1")
os.environ.setdefault("BW_ADMIN_KEY", "local-dev-key")

WEB_DIST = ROOT / "web" / "dist"


def _load_handlers() -> dict:
    """Import the Lambda handlers exactly as the deployed functions do."""
    import importlib.util

    handlers = {}
    for name in ("scan", "shelf", "search", "pharmacy", "admin"):
        spec = importlib.util.spec_from_file_location(
            f"bw_{name}_app", ROOT / "functions" / name / "app.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        handlers[name] = module.lambda_handler
    return handlers


HANDLERS = _load_handlers()

# (method regex, path regex) -> handler name. Mirrors template.yaml.
ROUTES = [
    (r"POST", r"^/scan/?$", "scan"),
    (r"GET|POST", r"^/shelf/?$", "shelf"),
    (r"DELETE", r"^/shelf/(?P<id>[^/]+)/?$", "shelf"),
    (r"GET", r"^/alerts/?$", "shelf"),
    (r"POST", r"^/pharmacy/check/?$", "pharmacy"),
    (r"GET", r"^/pharmacy/check/(?P<id>[^/]+)/?$", "pharmacy"),
    (r"GET", r"^/search/?$", "search"),
    (r"GET", r"^/stats/?$", "search"),
    (r"POST", r"^/admin/ingest/?$", "admin"),
]


def build_event(method: str, path: str, query: dict, headers: dict, body: str) -> tuple:
    for method_re, path_re, name in ROUTES:
        if not re.fullmatch(method_re, method):
            continue
        m = re.fullmatch(path_re, path)
        if not m:
            continue
        event = {
            "version": "2.0",
            "routeKey": f"{method} {path}",
            "rawPath": path,
            "headers": headers,
            "queryStringParameters": {k: v[0] for k, v in query.items()},
            "pathParameters": m.groupdict(),
            "body": body,
            "isBase64Encoded": False,
            "requestContext": {"http": {"method": method, "path": path}},
        }
        return event, HANDLERS[name]
    return None, None


class Handler(BaseHTTPRequestHandler):
    server_version = "BatchWatchLocal/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers", "content-type,authorization,x-admin-key,x-device-id"
        )
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        for k, v in (extra or {}).items():
            if k.lower() not in ("content-length", "content-type"):
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        headers = {k.lower(): v for k, v in self.headers.items()}

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""

        event, handler = build_event(method, path, query, headers, body)
        if handler:
            try:
                result = handler(event, None)
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "handler crashed - see server log"})
                return
            payload = result.get("body", "")
            self._send(
                result.get("statusCode", 200),
                payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode(),
                result.get("headers", {}).get("content-type", "application/json"),
                result.get("headers"),
            )
            return

        if method == "GET":
            self._serve_static(path)
            return
        self._json(404, {"error": f"no route for {method} {path}"})

    def _serve_static(self, path: str):
        if not WEB_DIST.exists():
            self._json(
                404,
                {
                    "error": f"no route for GET {path}",
                    "hint": "the web app is not built - run `npm install && npm run build` in web/",
                    "api": ["/stats", "/search?q=", "/scan", "/shelf", "/alerts"],
                },
            )
            return

        rel = path.lstrip("/") or "index.html"
        target = (WEB_DIST / rel).resolve()
        if not str(target).startswith(str(WEB_DIST.resolve())) or not target.is_file():
            target = WEB_DIST / "index.html"  # SPA fallback
        if not target.is_file():
            self._json(404, {"error": "not found"})
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    from batchwatch_common import bedrock
    from batchwatch_common.repo import corpus_stats, load_index

    index = load_index()
    stats = corpus_stats(index)

    print("BatchWatch local server")
    print(f"  store        LocalStore at {os.environ['BW_LOCAL_DIR']}")
    print(f"  corpus       {stats['rows']} NSQ rows, {stats['alert_months']} alert months")
    if stats["corpus_is_synthetic"]:
        print("               (SYNTHETIC sample data - not real CDSCO alerts)")
    if stats["rows"] == 0:
        print("               empty! run: python scripts/load_seed.py")
    bstat = bedrock.status()
    print(f"  bedrock      {'available' if bstat['available'] else 'off'} ({bstat['model']})")
    print(f"  web app      {'web/dist' if WEB_DIST.exists() else 'not built (API only)'}")
    print(f"  admin key    {os.environ['BW_ADMIN_KEY']}")
    print(f"\n  http://{args.host}:{args.port}\n")

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
