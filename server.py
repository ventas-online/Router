"""Minimal dependency-free web server for the Router Chat UI."""
from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from llmrouter import Router, build_providers_from_env, load_env

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def build_router() -> Router:
    env = load_env()
    priority = [x.strip() for x in env.get("PROVIDER_PRIORITY", "").split(",") if x.strip()]
    providers = build_providers_from_env(env, priority or None)
    return Router(providers=providers, max_retries=int(env.get("ROUTER_MAX_RETRIES", "1")))


ROUTER = build_router()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            return self._send(200, {"providers": ROUTER.status(), "skills": ROUTER.list_skills()})
        if path == "/api/health":
            return self._send(200, {"ok": True, "providers": len(ROUTER.providers())})
        if path == "/api/skills":
            return self._send(200, {"skills": ROUTER.list_skills()})
        return self._static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/chat":
            return self._send(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            messages = data.get("messages")
            if not isinstance(messages, list) or not messages:
                return self._send(400, {"error": "messages must be a non-empty list"})
            model = data.get("model") or None
            result = ROUTER.complete(messages, model=model, temperature=data.get("temperature"), max_tokens=data.get("max_tokens"))
            return self._send(200, result)
        except Exception as exc:
            return self._send(502, {"error": str(exc), "type": type(exc).__name__})

    def _static(self, path: str):
        relative = path.lstrip("/") or "index.html"
        target = (WEB / relative).resolve()
        if WEB not in target.parents and target != WEB:
            return self._send(403, {"error": "Forbidden"})
        if not target.is_file():
            target = WEB / "index.html"
        try:
            data = target.read_bytes()
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            return self._send(200, data, content_type)
        except OSError:
            return self._send(404, {"error": "Not found"})


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    print(f"Router Web UI: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
