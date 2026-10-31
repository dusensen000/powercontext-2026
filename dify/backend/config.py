"""Runtime configuration for the Memory Tavern backend.

Everything is overridable through environment variables so the evaluator can
point the service at their own seekdb directory and PowerContext server.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.environ.get("TAVERN_DATA_DIR", BASE_DIR / ".data"))
LOG_DIR = Path(os.environ.get("TAVERN_LOG_DIR", BASE_DIR / "logs"))
EVIDENCE_DIR = Path(os.environ.get("TAVERN_EVIDENCE_DIR", BASE_DIR.parent / "evidence"))
API = os.environ.get("TAVERN_API", "http://127.0.0.1:8770").rstrip("/")

# seekdb is the default and the configuration used for the submitted evidence.
# sqlite is only a convenience for quick local smoke tests on non-Linux hosts.
DB_BACKEND = os.environ.get("TAVERN_DB_BACKEND", "seekdb").strip().lower()
DB_PATH = str(Path(os.environ.get("TAVERN_DB_PATH", DATA_DIR / "tavern.db")))
DB_NAME = os.environ.get("TAVERN_DB_NAME", "tavern")

POWERCONTEXT_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
POWERCONTEXT_TOKEN = os.environ.get("POWERCONTEXT_TOKEN", "")

HOST = os.environ.get("TAVERN_HOST", "0.0.0.0")
PORT = int(os.environ.get("TAVERN_PORT", "8770"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
