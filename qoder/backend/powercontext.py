"""PowerContext HTTP 客户端：Source 证据、Memory 决定、PreparedContext 召回。

接口以运行中服务的 /openapi.json 为准：
  POST /v1/scopes                 {title, summary, idempotency_key}
  POST /v1/sources/content        {scope_id, source_id, content, metadata?}
  POST /v1/memory/remember        {scope_id, kind, text, reason?, expected_revision?}
  POST /v1/memory/search          {scope_id, query, limit?, mode?, tag_filter?}
  POST /v1/context/prepare        {scope_id, query, max_bytes?, explain?}
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .config import (
    POWERCONTEXT_BASE_URL,
    POWERCONTEXT_SCOPE_ID,
    POWERCONTEXT_TOKEN,
    SCOPE_FILE,
)

TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if POWERCONTEXT_TOKEN:
        headers["Authorization"] = f"Bearer {POWERCONTEXT_TOKEN}"
    return headers


def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{POWERCONTEXT_BASE_URL}{path}",
        json=payload,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def is_available() -> bool:
    try:
        response = httpx.get(
            f"{POWERCONTEXT_BASE_URL}/v1/server-info",
            headers=_headers(),
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def require_scope() -> str:
    """优先用 .env 里的 POWERCONTEXT_SCOPE_ID；没配就回落到 setup 脚本写下的文件。"""
    if POWERCONTEXT_SCOPE_ID:
        return POWERCONTEXT_SCOPE_ID
    if SCOPE_FILE.is_file():
        scope_id = json.loads(SCOPE_FILE.read_text(encoding="utf-8")).get("scope_id", "")
        if scope_id:
            return scope_id
    raise RuntimeError(
        "还没有 PowerContext Scope。先跑 scripts/setup_powercontext.py 建 Scope，"
        "把返回的 scope_id 写进 .env 再重试。"
    )


def save_scope(scope_id: str) -> None:
    SCOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_FILE.write_text(
        json.dumps({"scope_id": scope_id}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def create_scope(title: str, summary: str, idempotency_key: str) -> dict[str, Any]:
    return post(
        "/v1/scopes",
        {"title": title, "summary": summary, "idempotency_key": idempotency_key},
    )


def capture_source(
    source_id: str,
    content: str,
    *,
    scope_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scope_id": scope_id or require_scope(),
        "source_id": source_id,
        "content": content,
    }
    if metadata:
        payload["metadata"] = metadata
    return post("/v1/sources/content", payload)


def remember(
    kind: str,
    text: str,
    *,
    scope_id: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scope_id": scope_id or require_scope(),
        "kind": kind,
        "text": text,
    }
    if reason:
        payload["reason"] = reason
    return post("/v1/memory/remember", payload)


def search_memory(query: str, *, scope_id: str | None = None, limit: int = 10) -> dict[str, Any]:
    return post(
        "/v1/memory/search",
        {"scope_id": scope_id or require_scope(), "query": query, "limit": limit},
    )


def prepare_context(
    query: str,
    *,
    scope_id: str | None = None,
    max_bytes: int = 8000,
    explain: bool = True,
) -> dict[str, Any]:
    return post(
        "/v1/context/prepare",
        {
            "scope_id": scope_id or require_scope(),
            "query": query,
            "max_bytes": max_bytes,
            "explain": explain,
        },
    )
