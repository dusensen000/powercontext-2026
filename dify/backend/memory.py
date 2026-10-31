"""Thin PowerContext HTTP client used for cross-session episodic memory.

Only the documented v1 endpoints are used:
``POST /v1/scopes``, ``POST /v1/memory/remember`` and ``POST /v1/memory/search``.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

import config


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _log(action: str, detail: str) -> None:
    config.ensure_dirs()
    with (config.LOG_DIR / "powercontext.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{_now()}\t{action}\t{detail}\n")


class MemoryError_(RuntimeError):
    pass


class PowerContextClient:
    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        self.url = (url or config.POWERCONTEXT_URL).rstrip("/")
        self.token = token if token is not None else config.POWERCONTEXT_TOKEN

    # -- HTTP ------------------------------------------------------------------
    def _request(
        self, path: str, payload: Dict[str, Any] | None = None, timeout: int = 15
    ) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8") or "{}"
                elapsed = int((time.monotonic() - started) * 1000)
                _log("http", f"POST {path} status={response.status} elapsed_ms={elapsed} bytes={len(body)}")
                return json.loads(body)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            _log("error", f"POST {path} status={error.code} detail={detail[:300]}")
            raise MemoryError_(f"PowerContext {path} -> HTTP {error.code}: {detail[:500]}") from error
        except urllib.error.URLError as error:
            _log("error", f"POST {path} unreachable={error.reason}")
            raise MemoryError_(
                f"PowerContext unreachable at {self.url} ({error.reason}); "
                "start it with `powercontext server run --role all`"
            ) from error

    def health(self) -> bool:
        try:
            self._request("/v1/capabilities", timeout=5)
            return True
        except Exception:
            return False

    # -- API -------------------------------------------------------------------
    def ensure_scope(
        self,
        player_id: str,
        epoch: int,
        stored_scope: Optional[str] = None,
        persist: Optional[Callable[[str], None]] = None,
        nonce: str = "",
    ) -> str:
        if stored_scope:
            _log("scope", f"reuse player={player_id} epoch={epoch} scope_id={stored_scope}")
            return stored_scope
        title = f"tavern-{player_id}-e{epoch}" + (f"-{nonce}" if nonce else "")
        body = self._request(
            "/v1/scopes",
            {
                "title": title,
                "summary": f"记忆酒馆玩家 {player_id} 的跨会话互动记忆（第 {epoch} 世）",
                "idempotency_key": title,
            },
        )
        scope_id = body.get("scope_id") or body.get("scope", {}).get("scope_id")
        if not scope_id:
            raise MemoryError_(f"PowerContext returned no scope_id: {body}")
        if persist:
            persist(scope_id)
        _log("scope", f"create player={player_id} epoch={epoch} scope_id={scope_id} title={title}")
        return scope_id

    def remember(self, scope_id: str, text: str, reason: str) -> List[str]:
        body = self._request(
            "/v1/memory/remember",
            {"scope_id": scope_id, "kind": "episodic", "text": text, "reason": reason},
        )
        artifacts = []
        for record in body.get("records", []) or body.get("memories", []):
            artifact = record.get("artifact") if isinstance(record, dict) else None
            if isinstance(artifact, dict):
                artifacts.append(artifact.get("artifact_id", ""))
            elif artifact:
                artifacts.append(str(artifact))
        _log(
            "remember",
            f"scope={scope_id} chars={len(text)} artifacts={artifacts} preview={text[:120]!r}",
        )
        return artifacts

    def search(self, scope_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        body = self._request(
            "/v1/memory/search",
            {"scope_id": scope_id, "query": query, "limit": limit},
        )
        raw = body.get("hits") or body.get("records") or body.get("memories") or []
        hits: List[Dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            memory = entry.get("memory", entry)
            text = memory.get("text") or memory.get("content") or ""
            if not text:
                continue
            hits.append(
                {
                    "text": _clip(text),
                    "kind": memory.get("kind", ""),
                    "score": entry.get("score", memory.get("score")),
                    "created_at": memory.get("created_at") or memory.get("updated_at"),
                }
            )
        _log(
            "search",
            f"scope={scope_id} mode={body.get('mode')} hits={len(hits)} query={query[:80]!r}",
        )
        return hits[:limit]


def _clip(text: str, limit: int = 220) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"
