"""Seguimiento de tokens por proveedor con persistencia local en JSON."""
from __future__ import annotations
import json, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

class UsageTracker:
    def __init__(self, path: str = "usage.json"):
        self.path = None if path == ":memory:" else Path(path)
        self._lock = threading.Lock(); self._data: Dict[str, Any] = {"days": {}, "totals": {}}
        if self.path and self.path.exists():
            try: self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError): pass
    def _save(self):
        if self.path is None: return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(self.path)
        except OSError: pass
    @staticmethod
    def today(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    def record(self, provider: str, model: str, usage: Optional[Dict[str, Any]] = None, requests: int = 1):
        usage = usage or {}; prompt=int(usage.get("prompt_tokens") or 0); completion=int(usage.get("completion_tokens") or 0); day=self.today()
        with self._lock:
            entry=self._data["days"].setdefault(day, {}).setdefault(provider,{"prompt_tokens":0,"completion_tokens":0,"requests":0,"models":{}})
            entry["prompt_tokens"]+=prompt; entry["completion_tokens"]+=completion; entry["requests"]+=requests; entry["models"][model]=entry["models"].get(model,0)+1
            totals=self._data["totals"].setdefault(provider,{"prompt_tokens":0,"completion_tokens":0,"requests":0})
            totals["prompt_tokens"]+=prompt; totals["completion_tokens"]+=completion; totals["requests"]+=requests; self._save()
    def get_day_usage(self, provider: str, day: Optional[str] = None) -> int:
        entry=self._data["days"].get(day or self.today(),{}).get(provider); return 0 if not entry else int(entry.get("prompt_tokens",0))+int(entry.get("completion_tokens",0))
    def day_summary(self, day: Optional[str] = None): return self._data["days"].get(day or self.today(), {})
    def totals(self, provider: Optional[str] = None): return self._data["totals"].get(provider,{}) if provider else self._data["totals"]
