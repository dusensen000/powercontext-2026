"""Runtime configuration for the SDD context module.

All paths are derived from the ``minimax`` package root so that the module can be
executed from a clean checkout without hidden local state.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # .../minimax
SAMPLE = ROOT / "sample"
ARTIFACTS = ROOT / "artifacts"
DATA = ROOT / ".data"
WORK = ROOT / ".work"


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# Database backend: "seekdb" (default, Linux) or "sqlite" (local dev fallback).
DB_BACKEND = env("SDDCTX_DB_BACKEND", "seekdb")
DB_PATH = Path(env("SDDCTX_DB_PATH", str(DATA / "seekdb")))
DB_NAME = env("SDDCTX_DB_NAME", "sddctx")

# PowerContext state backend: "powercontext" (default) or "local" (offline dev).
STATE_BACKEND = env("POWERCONTEXT_STATE_BACKEND", "powercontext")
POWERCONTEXT_URL = (env("POWERCONTEXT_URL", "http://127.0.0.1:8000") or "").rstrip("/")
POWERCONTEXT_SCOPE = env("POWERCONTEXT_SCOPE")
POWERCONTEXT_TOKEN = env("POWERCONTEXT_TOKEN")

# MiniMax provider: "live" (default) or "stub" (offline smoke test).
PROVIDER = env("SDDCTX_PROVIDER", "live")
MINIMAX_API_KEY = env("MINIMAX_API_KEY")
MINIMAX_BASE_URL = (env("MINIMAX_BASE_URL", "https://api.minimaxi.com") or "").rstrip("/")
MINIMAX_MODEL = env("MINIMAX_MODEL", "MiniMax-M3")
# "minimax" uses /v1/text/chatcompletion_v2; "openai" uses /v1/chat/completions.
MINIMAX_PROTOCOL = env("MINIMAX_PROTOCOL", "minimax")

TASK = (
    "为 list_tasks 增加按 status 筛选的能力：status 非空时只返回该状态的任务，"
    "None 时返回全部；筛选必须在排序和分页之前完成，且不能破坏既有的排序、分页与输入校验行为。"
)


def ensure_dirs() -> None:
    for path in (ARTIFACTS, DATA, WORK):
        path.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "test_logs").mkdir(parents=True, exist_ok=True)
