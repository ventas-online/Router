"""Dependency-free web/API server for the Router AI workspace."""
from __future__ import annotations

import json, mimetypes, os, time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from llmrouter import Router, build_providers_from_env, load_env
from llmrouter.web_store import WebStore

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
MAX_BODY = int(os.getenv("ROUTER_MAX_BODY_BYTES", "1048576"))
STORE = WebStore(os.getenv("ROUTER_WEB_DB", str(ROOT / "router_web.sqlite3")))
RATE_WINDOW = int(os.getenv("ROUTER_RATE_WINDOW_SECONDS", "60"))
RATE_LIMIT = int(os.getenv("ROUTER_RATE_LIMIT", "30"))
AUTH_REQUIRED = os.getenv("ROUTER_AUTH_REQUIRED", "1").lower() not in ("0", "false", "no")
SESSION_TTL = int(os.getenv("ROUTER_SESSION_TTL_SECONDS", "604800"))
COOKIE_SECURE = os.getenv("ROUTER_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
_RATE_BUCKETS = defaultdict(deque)


def build_router():
    env = load_env()
    priority = [x.strip() for x in env.get("PROVIDER_PRIORITY", "").split(",") if x.strip()]
    return Router(providers=build_providers_from_env(env, priority or None), max_retries=int(env.get("ROUTER_MAX_RETRIES", "1")))


ROUTER = build_router()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _origin(self):
        return os.getenv("ROUTER_CORS_ORIGIN", "*")

    def _send(self, status, payload, content_type="application/json; charset=utf-8", extra_headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _rate_limited(self):
        if RATE_LIMIT <= 0:
            return False
        now = time.time()
        bucket = _RATE_BUCKETS[self.client_address[0]]
        while bucket and bucket[0] <= now - RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            return True
        bucket.append(now)
        return False

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("invalid Content-Length")
        if length < 0 or length > MAX_BODY:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    @staticmethod
    def _valid_messages(messages, allow_empty=False):
        if not isinstance(messages, list) or (not allow_empty and not messages) or len(messages) > 100:
            return False
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant", "system", "model"):
                return False
            if not isinstance(message.get("content", ""), str) or len(message.get("content", "")) > 100000:
                return False
        return True

    def _session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie.get("router_session").value if cookie.get("router_session") else None
        except Exception:
            return None

    def _current_user(self):
        return STORE.get_user_by_session(self._session_token())

    def _require_user(self):
        if not AUTH_REQUIRED:
            return {"id": "anonymous", "email": "anonymous"}
        user = self._current_user()
        if not user:
            self._send(401, {"error": "Authentication required", "code": "AUTH_REQUIRED"})
            return None
        return user

    def _set_session_cookie(self, token):
        parts = ["router_session=" + token, "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=" + str(SESSION_TTL)]
        if COOKIE_SECURE:
            parts.append("Secure")
        return {"Set-Cookie": "; ".join(parts)}

    @staticmethod
    def _clear_session_cookie():
        return {"Set-Cookie": "router_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"}

    @staticmethod
    def _valid_credentials(data):
        email = data.get("email") if isinstance(data, dict) else None
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(email, str) or not 3 <= len(email.strip()) <= 254 or "@" not in email:
            return False
        if not isinstance(password, str) or not 10 <= len(password) <= 256:
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/") and self._rate_limited():
            return self._send(429, {"error": "Too many requests"})
        if path == "/api/health":
            return self._send(200, {"ok": True, "providers": len(ROUTER.providers()), "version": "web-v5-auth"})
        if path == "/api/auth/me":
            user = self._current_user()
            return self._send(200, {"authenticated": bool(user), "user": user})
        user = self._require_user()
        if not user:
            return
        if path == "/api/status":
            return self._send(200, {"providers": ROUTER.status(), "skills": ROUTER.list_skills()})
        if path == "/api/skills":
            return self._send(200, {"skills": ROUTER.list_skills()})
        if path == "/api/conversations":
            return self._send(200, {"conversations": STORE.list_conversations(user["id"])})
        if path.startswith("/api/conversations/"):
            item = STORE.get_conversation(user["id"], path.rsplit("/", 1)[-1])
            return self._send(200, item) if item else self._send(404, {"error": "Conversation not found"})
        if path == "/api/analytics":
            return self._send(200, STORE.analytics(user["id"]))
        return self._static(path)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if self._rate_limited():
            return self._send(429, {"error": "Too many requests"})
        user = self._require_user()
        if not user:
            return
        if path.startswith("/api/conversations/"):
            STORE.delete_conversation(user["id"], path.rsplit("/", 1)[-1])
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "Not found"})

    def _stream_chat(self, data, messages, conversation_id, started, user_id):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        answer, usage, meta, ok = [], {}, {}, False
        try:
            for event in ROUTER.stream(messages, model=data.get("model") or None, temperature=data.get("temperature"), max_tokens=data.get("max_tokens")):
                if event.get("type") == "delta":
                    answer.append(event.get("content", ""))
                if event.get("type") == "usage":
                    usage = event.get("usage") or usage
                meta.update({k: event[k] for k in ("model", "provider") if k in event})
                self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
            ok = True
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            result = {"content": "".join(answer), "model": meta.get("model"), "provider": meta.get("provider"), "usage": usage}
            STORE.record_request(user_id=user_id, conversation_id=conversation_id, model=result.get("model"), provider=result.get("provider"), latency_ms=(time.perf_counter() - started) * 1000, prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"), ok=True)
            if conversation_id:
                STORE.save_conversation(user_id, conversation_id, next((m.get("content", "New chat") for m in messages if m.get("role") == "user"), "New chat"), messages + [{"role": "assistant", "content": result["content"]}])
        except Exception as exc:
            STORE.record_request(user_id=user_id, conversation_id=conversation_id, model=data.get("model"), latency_ms=(time.perf_counter() - started) * 1000, ok=False, error_type=type(exc).__name__)
            try:
                self.wfile.write(("data: " + json.dumps({"type": "error", "error": "Router could not complete the request", "code": type(exc).__name__}) + "\n\n").encode())
                self.wfile.flush()
            except OSError:
                pass
        if not ok:
            return

    def do_POST(self):
        path = urlparse(self.path).path
        if self._rate_limited():
            return self._send(429, {"error": "Too many requests"})
        try:
            data = self._json_body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400 if isinstance(exc, json.JSONDecodeError) else 413, {"error": str(exc)})

        if path == "/api/auth/register":
            if not self._valid_credentials(data):
                return self._send(400, {"error": "Use a valid email and a password of at least 10 characters"})
            user = STORE.create_user(data["email"], data["password"])
            if not user:
                return self._send(409, {"error": "An account with that email already exists"})
            token = STORE.create_session(user["id"], SESSION_TTL)
            return self._send(201, {"user": user}, extra_headers=self._set_session_cookie(token))

        if path == "/api/auth/login":
            if not self._valid_credentials(data):
                return self._send(400, {"error": "Invalid credentials"})
            user = STORE.authenticate_user(data["email"], data["password"])
            if not user:
                return self._send(401, {"error": "Invalid email or password"})
            token = STORE.create_session(user["id"], SESSION_TTL)
            return self._send(200, {"user": user}, extra_headers=self._set_session_cookie(token))

        if path == "/api/auth/logout":
            STORE.delete_session(self._session_token())
            return self._send(200, {"ok": True}, extra_headers=self._clear_session_cookie())

        user = self._require_user()
        if not user:
            return
        if path == "/api/conversations":
            messages = data.get("messages", [])
            if not self._valid_messages(messages, allow_empty=True):
                return self._send(400, {"error": "invalid messages: expected up to 100 valid messages"})
            title = data.get("title", "New chat")
            if not isinstance(title, str):
                return self._send(400, {"error": "title must be a string"})
            return self._send(201, {"id": STORE.save_conversation(user["id"], data.get("id"), title, messages)})
        if path != "/api/chat":
            return self._send(404, {"error": "Not found"})

        started = time.perf_counter()
        conversation_id = None
        try:
            messages = data.get("messages")
            if not self._valid_messages(messages):
                return self._send(400, {"error": "invalid messages: expected 1-100 valid messages"})
            conversation_id = data.get("conversation_id")
            if conversation_id is not None and not isinstance(conversation_id, str):
                return self._send(400, {"error": "conversation_id must be a string"})
            if conversation_id and not STORE.get_conversation(user["id"], conversation_id):
                return self._send(404, {"error": "Conversation not found"})
            if data.get("stream") is True:
                return self._stream_chat(data, messages, conversation_id, started, user["id"])
            result = ROUTER.complete(messages, model=data.get("model") or None, temperature=data.get("temperature"), max_tokens=data.get("max_tokens"))
            usage = result.get("usage") or {}
            STORE.record_request(user_id=user["id"], conversation_id=conversation_id, model=result.get("model", data.get("model")), provider=result.get("provider"), latency_ms=(time.perf_counter() - started) * 1000, prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"), ok=True)
            if conversation_id:
                STORE.save_conversation(user["id"], conversation_id, next((m.get("content", "New chat") for m in messages if m.get("role") == "user"), "New chat"), messages + [{"role": "assistant", "content": result.get("content", "")}])
            return self._send(200, result)
        except Exception as exc:
            STORE.record_request(user_id=user["id"], conversation_id=conversation_id, model=data.get("model"), latency_ms=(time.perf_counter() - started) * 1000, ok=False, error_type=type(exc).__name__)
            return self._send(502, {"error": "Router could not complete the request", "type": type(exc).__name__})

    def _static(self, path):
        target = (WEB / (path.lstrip("/") or "index.html")).resolve()
        if WEB not in target.parents and target != WEB:
            return self._send(403, {"error": "Forbidden"})
        if not target.is_file():
            target = WEB / "index.html"
        try:
            return self._send(200, target.read_bytes(), mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        except OSError:
            return self._send(404, {"error": "Not found"})


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    print(f"Router Web UI: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
