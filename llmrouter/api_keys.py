"""Persistent project API keys, quotas, and billing-ready usage metering."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class QuotaExceeded(Exception):
    def __init__(self, kind, limit, used):
        self.kind = kind
        self.limit = int(limit)
        self.used = int(used)
        super().__init__(f"{kind} quota exceeded")


class ApiKeyStore:
    """SQLite-backed API key service. Raw keys are never persisted."""

    def __init__(self, path="router_web.sqlite3"):
        self.path = str(Path(path))
        self._lock = threading.Lock()
        self._init()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init(self):
        with self._lock, self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                requests_per_day INTEGER NOT NULL DEFAULT 1000,
                tokens_per_day INTEGER NOT NULL DEFAULT 1000000,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_used_at REAL,
                revoked_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_api_keys_project ON api_keys(project_id);
            CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                api_key_id TEXT,
                model TEXT,
                provider TEXT,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                ok INTEGER NOT NULL,
                error_type TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_usage_project_time ON usage_events(project_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_events(user_id, created_at);
            """)

    @staticmethod
    def _hash_key(raw_key):
        return hashlib.sha256(raw_key.encode("ascii")).hexdigest()

    @staticmethod
    def _generate_key():
        return "rtr_live_" + secrets.token_urlsafe(32)

    def create_project(self, user_id, name, requests_per_day=1000, tokens_per_day=1_000_000):
        project_id = uuid.uuid4().hex
        now = time.time()
        name = (name or "Default project").strip()[:120] or "Default project"
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO projects(id,user_id,name,requests_per_day,tokens_per_day,created_at) VALUES(?,?,?,?,?,?)",
                (project_id, user_id, name, max(0, int(requests_per_day)), max(0, int(tokens_per_day)), now),
            )
        return self.get_project(user_id, project_id)

    def list_projects(self, user_id):
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,requests_per_day,tokens_per_day,created_at FROM projects WHERE user_id=? ORDER BY created_at",
                (user_id,),
            ).fetchall()]

    def get_project(self, user_id, project_id):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
            return dict(row) if row else None

    def delete_project(self, user_id, project_id):
        with self._lock, self._connect() as db:
            cur = db.execute("DELETE FROM projects WHERE id=? AND user_id=?", (project_id, user_id))
            return cur.rowcount > 0

    def create_key(self, user_id, project_id, name="API key"):
        raw = self._generate_key()
        key_id = uuid.uuid4().hex
        now = time.time()
        prefix = raw[:16]
        name = (name or "API key").strip()[:120] or "API key"
        with self._lock, self._connect() as db:
            owned = db.execute("SELECT 1 FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
            if not owned:
                return None
            db.execute(
                "INSERT INTO api_keys(id,project_id,key_prefix,key_hash,name,created_at) VALUES(?,?,?,?,?,?)",
                (key_id, project_id, prefix, self._hash_key(raw), name, now),
            )
        return {"id": key_id, "project_id": project_id, "name": name, "prefix": prefix, "key": raw, "created_at": now}

    def list_keys(self, user_id, project_id):
        with self._lock, self._connect() as db:
            rows = db.execute("""
                SELECT k.id,k.project_id,k.key_prefix,k.name,k.created_at,k.last_used_at,k.revoked_at
                FROM api_keys k JOIN projects p ON p.id=k.project_id
                WHERE k.project_id=? AND p.user_id=? ORDER BY k.created_at DESC
            """, (project_id, user_id)).fetchall()
            return [dict(row) for row in rows]

    def revoke_key(self, user_id, project_id, key_id):
        now = time.time()
        with self._lock, self._connect() as db:
            cur = db.execute("""
                UPDATE api_keys SET revoked_at=? WHERE id=? AND project_id=?
                AND EXISTS (SELECT 1 FROM projects WHERE id=? AND user_id=?)
                AND revoked_at IS NULL
            """, (now, key_id, project_id, project_id, user_id))
            return cur.rowcount > 0

    def authenticate_key(self, raw_key):
        if not isinstance(raw_key, str) or not raw_key.startswith("rtr_live_"):
            return None
        digest = self._hash_key(raw_key)
        with self._lock, self._connect() as db:
            row = db.execute("""
                SELECT k.id api_key_id,k.project_id,p.user_id,p.name project_name,
                       p.requests_per_day,p.tokens_per_day,k.revoked_at
                FROM api_keys k JOIN projects p ON p.id=k.project_id
                WHERE k.key_hash=?
            """, (digest,)).fetchone()
            if not row or row["revoked_at"] is not None:
                return None
            db.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (time.time(), row["api_key_id"]))
            return dict(row)

    def quota_usage(self, project_id, now=None):
        now = now or time.time()
        since = now - 86400
        with self._lock, self._connect() as db:
            row = db.execute("""
                SELECT COUNT(*) requests, COALESCE(SUM(prompt_tokens+completion_tokens),0) tokens
                FROM usage_events WHERE project_id=? AND created_at>=?
            """, (project_id, since)).fetchone()
            return {"requests": int(row["requests"]), "tokens": int(row["tokens"])}

    def check_quota(self, project_id, additional_tokens=0, now=None):
        now = now or time.time()
        with self._lock, self._connect() as db:
            project = db.execute("SELECT requests_per_day,tokens_per_day FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                return False
            since = now - 86400
            usage = db.execute("""
                SELECT COUNT(*) requests, COALESCE(SUM(prompt_tokens+completion_tokens),0) tokens
                FROM usage_events WHERE project_id=? AND created_at>=?
            """, (project_id, since)).fetchone()
            requests = int(usage["requests"])
            tokens = int(usage["tokens"])
            if int(project["requests_per_day"]) and requests >= int(project["requests_per_day"]):
                raise QuotaExceeded("requests_per_day", project["requests_per_day"], requests)
            projected = tokens + max(0, int(additional_tokens or 0))
            if int(project["tokens_per_day"]) and projected > int(project["tokens_per_day"]):
                raise QuotaExceeded("tokens_per_day", project["tokens_per_day"], tokens)
            return True

    def record_usage(self, user_id, project_id, api_key_id=None, **data):
        with self._lock, self._connect() as db:
            db.execute("""
                INSERT INTO usage_events(user_id,project_id,api_key_id,model,provider,prompt_tokens,
                completion_tokens,latency_ms,ok,error_type,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                user_id, project_id, api_key_id, data.get("model"), data.get("provider"),
                max(0, int(data.get("prompt_tokens") or 0)), max(0, int(data.get("completion_tokens") or 0)),
                max(0, int(data.get("latency_ms") or 0)), 1 if data.get("ok") else 0,
                data.get("error_type"), time.time(),
            ))

    def usage_report(self, user_id, project_id, hours=24):
        since = time.time() - max(1, int(hours)) * 3600
        with self._lock, self._connect() as db:
            row = db.execute("""
                SELECT COUNT(*) requests, COALESCE(SUM(prompt_tokens),0) prompt_tokens,
                COALESCE(SUM(completion_tokens),0) completion_tokens,
                COALESCE(AVG(latency_ms),0) avg_latency_ms,
                SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) successes
                FROM usage_events WHERE project_id=? AND user_id=? AND created_at>=?
            """, (project_id, user_id, since)).fetchone()
            return {
                "hours": int(hours), "requests": int(row["requests"]),
                "prompt_tokens": int(row["prompt_tokens"]), "completion_tokens": int(row["completion_tokens"]),
                "tokens": int(row["prompt_tokens"]) + int(row["completion_tokens"]),
                "successes": int(row["successes"] or 0),
                "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
            }
