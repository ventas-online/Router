"""Dependency-free SQLite persistence for the Router web workspace."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class WebStore:
    def __init__(self, path="router_web.sqlite3"):
        self.path = str(Path(path))
        self._lock = threading.Lock()
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self):
        with self._lock, self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT NOT NULL,
                messages TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                conversation_id TEXT,
                model TEXT,
                provider TEXT,
                latency_ms INTEGER,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                ok INTEGER NOT NULL,
                error_type TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_requests_user_created ON requests(user_id, created_at);
            """)
            self._ensure_column(db, "conversations", "user_id", "TEXT")
            self._ensure_column(db, "requests", "user_id", "TEXT")

    @staticmethod
    def _ensure_column(db, table, column, definition):
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _hash_password(password, salt=None):
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
        return "pbkdf2_sha256$210000$%s$%s" % (salt.hex(), digest.hex())

    @staticmethod
    def _verify_password(password, encoded):
        try:
            scheme, rounds, salt_hex, digest_hex = encoded.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _normalize_email(email):
        return email.strip().lower()

    def create_user(self, email, password):
        email = self._normalize_email(email)
        now = time.time()
        user_id = uuid.uuid4().hex
        encoded = self._hash_password(password)
        with self._lock, self._connect() as db:
            try:
                db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)", (user_id, email, encoded, now))
            except sqlite3.IntegrityError:
                return None
        return {"id": user_id, "email": email, "created_at": now}

    def authenticate_user(self, email, password):
        email = self._normalize_email(email)
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or not self._verify_password(password, row["password_hash"]):
            return None
        return {"id": row["id"], "email": row["email"], "created_at": row["created_at"]}

    def create_session(self, user_id, ttl_seconds=604800):
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)", (self._token_hash(token), user_id, now, now + int(ttl_seconds)))
            db.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
        return token

    def get_user_by_session(self, token):
        if not token:
            return None
        with self._lock, self._connect() as db:
            row = db.execute("""
                SELECT u.id,u.email,u.created_at FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>?
            """, (self._token_hash(token), time.time())).fetchone()
        return dict(row) if row else None

    def delete_session(self, token):
        if not token:
            return
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (self._token_hash(token),))

    def list_conversations(self, user_id, limit=30):
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                (user_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_conversation(self, user_id, conversation_id):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["messages"] = json.loads(item["messages"])
            return item

    def save_conversation(self, user_id, conversation_id, title, messages):
        now = time.time()
        conversation_id = conversation_id or uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute("""
                INSERT INTO conversations(id,user_id,title,messages,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                messages=excluded.messages,updated_at=excluded.updated_at
                WHERE conversations.user_id=excluded.user_id
            """, (conversation_id, user_id, title[:120] or "New chat", json.dumps(messages, ensure_ascii=False), now, now))
        return conversation_id

    def delete_conversation(self, user_id, conversation_id):
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id))

    def record_request(self, **data):
        with self._lock, self._connect() as db:
            db.execute("""
                INSERT INTO requests(user_id,conversation_id,model,provider,latency_ms,prompt_tokens,
                completion_tokens,ok,error_type,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                data.get("user_id"), data.get("conversation_id"), data.get("model"), data.get("provider"),
                int(data.get("latency_ms") or 0), int(data.get("prompt_tokens") or 0),
                int(data.get("completion_tokens") or 0), 1 if data.get("ok") else 0,
                data.get("error_type"), time.time(),
            ))

    def analytics(self, user_id, hours=24):
        since = time.time() - int(hours) * 3600
        with self._lock, self._connect() as db:
            total = db.execute("SELECT COUNT(*) n FROM requests WHERE user_id=? AND created_at>=?", (user_id, since)).fetchone()["n"]
            ok = db.execute("SELECT COUNT(*) n FROM requests WHERE user_id=? AND created_at>=? AND ok=1", (user_id, since)).fetchone()["n"]
            avg = db.execute("SELECT AVG(latency_ms) n FROM requests WHERE user_id=? AND created_at>=? AND ok=1", (user_id, since)).fetchone()["n"]
            by_provider = db.execute("""
                SELECT COALESCE(provider,'unknown') provider, COUNT(*) requests,
                SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) successes,
                SUM(prompt_tokens+completion_tokens) tokens
                FROM requests WHERE user_id=? AND created_at>=? GROUP BY provider ORDER BY requests DESC
            """, (user_id, since)).fetchall()
            return {
                "hours": int(hours), "requests": total, "successes": ok,
                "success_rate": round((ok / total) * 100, 2) if total else 0,
                "avg_latency_ms": round(avg, 1) if avg is not None else 0,
                "providers": [dict(r) for r in by_provider],
            }
