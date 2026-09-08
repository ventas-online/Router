"""Carga de variables de entorno desde .env (sin dependencias externas)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def load_env(path: str | Path | None = None) -> Dict[str, str]:
    """Lee un archivo .env (si existe) y devuelve un dict con las variables.

    Las variables ya presentes en os.environ tienen prioridad (no se pisan).
    """
    env: Dict[str, str] = {}
    if path is None:
        path = Path(__file__).resolve().parent.parent / ".env"
    path = Path(path)

    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in env:
                env[key] = value

    for key, value in os.environ.items():
        env[key] = value
    return env
