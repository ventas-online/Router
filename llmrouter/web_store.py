"""Small SQLite persistence layer for the Router web workspace.

Uses only the Python standard library so the core project remains dependency-free.
"""
from __future__ import annotations

import json
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
        return conn

    def _init(self):
        with self._lock, self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                messages TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
            """)

    def list_conversations(self, limit=30):
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_conversation(self, conversation_id):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["messages"] = json.loads(item["messages"])
            return item

    def save_conversation(self, conversation_id, title, messages):
        now = time.time()
        conversation_id = conversation_id or uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute("""
                INSERT INTO conversations(id,title,messages,created_at,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                messages=excluded.messages,updated_at=excluded.updated_at
            """, (conversation_id, title[:120] or "New chat", json.dumps(messages, ensure_ascii=False), now, now))
        return conversation_id

    def delete_conversation(self, conversation_id):
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    def record_request(self, **data):
        with self._lock, self._connect() as db:
            db.execute("""
                INSERT INTO requests(conversation_id,model,provider,latency_ms,prompt_tokens,
                completion_tokens,ok,error_type,created_at) VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                data.get("conversation_id"), data.get("model"), data.get("provider"),
                int(data.get("latency_ms") or 0), int(data.get("prompt_tokens") or 0),
                int(data.get("completion_tokens") or 0), 1 if data.get("ok") else 0,
                data.get("error_type"), time.time(),
            ))

    def analytics(self, hours=24):
        since = time.time() - int(hours) * 3600
        with self._lock, self._connect() as db:
            total = db.execute("SELECT COUNT(*) n FROM requests WHERE created_at>=?", (since,)).fetchone()["n"]
            ok = db.execute("SELECT COUNT(*) n FROM requests WHERE created_at>=? AND ok=1", (since,)).fetchone()["n"]
            avg = db.execute("SELECT AVG(latency_ms) n FROM requests WHERE created_at>=? AND ok=1", (since,)).fetchone()["n"]
            by_provider = db.execute("""
                SELECT COALESCE(provider,'unknown') provider, COUNT(*) requests,
                SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) successes,
                SUM(prompt_tokens+completion_tokens) tokens
                FROM requests WHERE created_at>=? GROUP BY provider ORDER BY requests DESC
            """, (since,)).fetchall()
            return {
                "hours": int(hours), "requests": total, "successes": ok,
                "success_rate": round((ok / total) * 100, 2) if total else 0,
                "avg_latency_ms": round(avg, 1) if avg is not None else 0,
                "providers": [dict(r) for r in by_provider],
            }
