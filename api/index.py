"""Vercel Python ASGI entrypoint for Kyro ClientOS."""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# This entrypoint must never silently select temporary/local SQLite on Vercel.
_previous_vercel = os.environ.get("VERCEL")
os.environ["VERCEL"] = "1"
try:
    import server as kyro  # noqa: E402
finally:
    if _previous_vercel is None:
        os.environ.pop("VERCEL", None)
    else:
        os.environ["VERCEL"] = _previous_vercel
kyro.VERCEL_RUNTIME = True


_DB_INIT_LOCK = threading.Lock()
_DB_READY = False


def _ensure_database() -> None:
    global _DB_READY
    if _DB_READY:
        return
    with _DB_INIT_LOCK:
        if not _DB_READY:
            kyro.init_db()
            _DB_READY = True


class _Headers:
    def __init__(self, raw_headers: list[tuple[bytes, bytes]]):
        self._items: dict[str, str] = {}
        for raw_key, raw_value in raw_headers:
            key = raw_key.decode("latin-1").lower()
            value = raw_value.decode("latin-1")
            if key in self._items:
                separator = "; " if key == "cookie" else ", "
                self._items[key] += separator + value
            else:
                self._items[key] = value

    def get(self, key: str, default: str = "") -> str:
        return self._items.get(key.lower(), default)


class _VercelRequest(kyro.KyroHandler):
    """Minimal BaseHTTPRequestHandler-shaped adapter for the Kyro ClientOS route logic."""

    def __init__(self, method: str, path: str, headers: _Headers, client: tuple[str, int]):
        self.command = method
        self.path = path
        self.headers = headers
        self.client_address = client
        self.status_code = 200
        self.response_headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status_code = code

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers.append((keyword, value))

    def end_headers(self) -> None:
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._send_json(code, {"error": message or "Not found.", "code": "not_found"})

    def address_string(self) -> str:
        return self.client_address[0]

    def _response(self) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        body = self.wfile.getvalue()
        headers = [(key.lower().encode("latin-1"), value.encode("latin-1"))
                   for key, value in self.response_headers]
        if not any(key == b"content-length" for key, _ in headers):
            headers.append((b"content-length", str(len(body)).encode("ascii")))
        return self.status_code, headers, body


def _route_path(scope: dict[str, Any], query: dict[str, list[str]]) -> str:
    path = unquote(scope.get("path", "/"))
    # vercel.json rewrites /api/<route> to the single Python function at /api/index.
    # Vercel passes the named wildcard parameter through as a query value.
    if path in ("/api/index", "/api") and query.get("kyro_route"):
        pieces = query.pop("kyro_route")
        value = pieces[0] if pieces else ""
        if isinstance(value, list):
            value = "/".join(value)
        route = unquote(str(value)).strip("/")
        path = "/api/" + route if route else "/api"
    return path


def _dispatch(method: str, path: str, query: dict[str, list[str]], body: dict,
              headers: _Headers, client: tuple[str, int]) -> _VercelRequest:
    request = _VercelRequest(method, path, headers, client)
    if path == "/healthz" and method in ("GET", "HEAD"):
        request._send_json(200, {"ok": True, "service": "Kyro Outreach"})
    elif path == "/api/bootstrap" and method == "GET":
        _ensure_database()
        request._bootstrap()
    elif path.startswith("/api/"):
        _ensure_database()
        request._api(method, path, query, body)
    elif method == "GET" and path in ("/", "/index.html"):
        request._static(kyro.PUBLIC / "index.html")
    elif method == "GET":
        request._static(kyro.PUBLIC / path.lstrip("/"))
    else:
        request._send_json(405, {"error": "Method not allowed.", "code": "method_not_allowed"})
    return request


async def app(scope: dict[str, Any], receive, send) -> None:
    """ASGI app recognized by Vercel's Python Functions runtime."""
    if scope.get("type") != "http":
        return

    method = scope.get("method", "GET").upper()
    headers = _Headers(scope.get("headers", []))
    try:
        query_string = scope.get("query_string", b"").decode("latin-1")
        query = parse_qs(query_string, keep_blank_values=True)
        path = _route_path(scope, query)
        body_bytes = bytearray()
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    return
                if message.get("type") != "http.request":
                    continue
                body_bytes.extend(message.get("body", b""))
                if len(body_bytes) > 2_000_000:
                    raise kyro.APIError(413, "This request is too large.", "body_too_large")
                if not message.get("more_body", False):
                    break
        if body_bytes:
            try:
                body = json.loads(body_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise kyro.APIError(400, "Request data could not be read.", "invalid_json") from None
            if not isinstance(body, dict):
                raise kyro.APIError(400, "Request data must be an object.", "invalid_json")
        else:
            body = {}

        raw_client = scope.get("client") or (headers.get("x-forwarded-for", "127.0.0.1").split(",", 1)[0].strip(), 0)
        client = (str(raw_client[0]), int(raw_client[1]) if len(raw_client) > 1 else 0)
        request = await asyncio.to_thread(_dispatch, method, path, query, body, headers, client)
        status, response_headers, response_body = request._response()
    except kyro.APIError as exc:
        status = exc.status
        response_body = json.dumps({"error": exc.message, "code": exc.code}, ensure_ascii=False).encode("utf-8")
        response_headers = [(b"content-type", b"application/json; charset=utf-8"),
                            (b"cache-control", b"no-store"),
                            (b"content-length", str(len(response_body)).encode("ascii"))]
    except Exception as exc:
        print(f"Vercel function error: {type(exc).__name__}")
        response_body = json.dumps({"error": "Something went wrong. Your data was not changed.",
                                    "code": "internal_error"}).encode("utf-8")
        status = 500
        response_headers = [(b"content-type", b"application/json; charset=utf-8"),
                            (b"cache-control", b"no-store"),
                            (b"content-length", str(len(response_body)).encode("ascii"))]

    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": response_body})
