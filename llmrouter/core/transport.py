"""Transporte HTTP mínimo con urllib (stdlib)."""
from __future__ import annotations
import json, urllib.error, urllib.request
from typing import Any, Dict, Iterator, Tuple


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


def http_post_sse(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int = 60) -> Iterator[Tuple[int, str]]:
    """Yield (status, SSE data) without buffering the response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={**headers, "Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        yield e.code, raw
        return
    except urllib.error.URLError as e:
        yield 0, json.dumps({"error": {"message": f"network: {e.reason}"}})
        return

    with resp:
        buffer = ""
        while True:
            chunk = resp.readline()
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if line.startswith("data:"):
                    yield resp.status, line[5:].lstrip()
        if buffer.startswith("data:"):
            yield resp.status, buffer[5:].lstrip()
