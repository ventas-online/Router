"""Transporte HTTP mínimo con urllib (stdlib). Devuelve (status, dict)."""
from __future__ import annotations
import json, urllib.error, urllib.request
from typing import Any, Dict, Tuple

def http_post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int = 60) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try: body = json.loads(raw) if raw else {}
            except json.JSONDecodeError: body = {"raw": raw}
            return resp.status, body
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try: body = json.loads(raw) if raw else {}
        except json.JSONDecodeError: body = {"error": {"message": raw[:500]}}
        return e.code, body
    except urllib.error.URLError as e:
        return 0, {"error": {"message": f"network: {e.reason}"}}
