"""Persist development-task state so a later session (or another agent) can resume.

Default backend is a local **PowerContext** server: the record is written with
``POST /v1/memory/remember`` and retrieved with ``POST /v1/memory/search``, which
demonstrates that progress lives outside the process and outside the repo.
``local`` writes the same JSON to ``.data/state.json`` for offline runs.
"""

from __future__ import annotations

import datetime as _dt
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

MARKER = "SDDCTX_STATE_V1"
SCOPE_CACHE = config.DATA / "scope.json"
TASK_TITLE = "sddctx-taskboard"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _log(action: str, backend: str, detail: str) -> None:
    config.ensure_dirs()
    with (config.ARTIFACTS / "state_ops.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{_now()}\tbackend={backend}\taction={action}\t{detail}\n")


class StateStore:
    backend = config.STATE_BACKEND

    def save(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def load(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class LocalStateStore(StateStore):
    backend = "local"

    def __init__(self) -> None:
        self.path = config.DATA / "state.json"

    def save(self, record: Dict[str, Any]) -> Dict[str, Any]:
        config.ensure_dirs()
        self.path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        _log("save", self.backend, f"path={self.path} bytes={self.path.stat().st_size}")
        return {"backend": self.backend, "path": str(self.path)}

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.path.is_file():
            _log("load", self.backend, "missing")
            return None
        record = json.loads(self.path.read_text(encoding="utf-8"))
        _log("load", self.backend, f"task_id={record.get('task_id')}")
        return record


class PowerContextStateStore(StateStore):
    backend = "powercontext"

    def __init__(self) -> None:
        self.url = config.POWERCONTEXT_URL
        self.token = config.POWERCONTEXT_TOKEN
        self.scope_id = config.POWERCONTEXT_SCOPE or self._cached_scope()

    # -- HTTP ------------------------------------------------------------------
    def _request(self, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.url}{path}", data=data, headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8") or "{}"
                return json.loads(body)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"PowerContext {path} -> HTTP {error.code}: {detail[:500]}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"PowerContext unreachable at {self.url} ({error.reason}); "
                "start the server or set POWERCONTEXT_STATE_BACKEND=local"
            ) from error

    def _cached_scope(self) -> Optional[str]:
        if SCOPE_CACHE.is_file():
            return json.loads(SCOPE_CACHE.read_text(encoding="utf-8")).get("scope_id")
        return None

    def ensure_scope(self) -> str:
        if self.scope_id:
            return self.scope_id
        body = self._request(
            "/v1/scopes",
            {
                "title": TASK_TITLE,
                "summary": "SDD context module for the taskboard sample project",
                "idempotency_key": TASK_TITLE,
            },
        )
        scope_id = body.get("scope_id") or body.get("scope", {}).get("scope_id")
        if not scope_id:
            raise RuntimeError(f"PowerContext returned no scope_id: {body}")
        self.scope_id = scope_id
        config.ensure_dirs()
        SCOPE_CACHE.write_text(json.dumps({"scope_id": scope_id}), encoding="utf-8")
        _log("scope", self.backend, f"scope_id={scope_id}")
        return scope_id

    # -- API -------------------------------------------------------------------
    def save(self, record: Dict[str, Any]) -> Dict[str, Any]:
        scope_id = self.ensure_scope()
        text = MARKER + "\n" + json.dumps(record, ensure_ascii=False, sort_keys=True)
        body = self._request(
            "/v1/memory/remember",
            {
                "scope_id": scope_id,
                "kind": "decision",
                "text": text,
                "reason": f"SDD task progress for {record.get('task_id')}",
            },
        )
        artifacts = [
            r.get("artifact", {}).get("artifact_id") if isinstance(r.get("artifact"), dict)
            else r.get("artifact")
            for r in body.get("records", [])
        ]
        _log(
            "save", self.backend,
            f"scope={scope_id} task_id={record.get('task_id')} artifacts={artifacts}",
        )
        return {"backend": self.backend, "scope_id": scope_id, "artifacts": artifacts}

    def _records(self, body: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Search returns {"mode": "text", "hits": [{"memory": {...}}]}; other
        # endpoints return a flat {"records": [...]} list.
        for key in ("records", "memories", "hits", "data", "items"):
            value = body.get(key)
            if isinstance(value, list):
                return [
                    item.get("memory", item) if isinstance(item, dict) else item
                    for item in value
                ]
        return []

    def load(self) -> Optional[Dict[str, Any]]:
        scope_id = self.ensure_scope()
        body = self._request(
            "/v1/memory/search",
            {
                "scope_id": scope_id,
                "query": f"{MARKER} taskboard list_tasks status filter",
                "limit": 10,
            },
        )
        candidates: List[Dict[str, Any]] = []
        for entry in self._records(body):
            text = entry.get("text") or entry.get("content") or ""
            if MARKER not in text:
                continue
            try:
                candidates.append(json.loads(text.split(MARKER, 1)[1].strip()))
            except json.JSONDecodeError:
                continue
        if not candidates:
            _log("load", self.backend, f"scope={scope_id} no records")
            return None
        record = max(candidates, key=lambda r: str(r.get("updated_at", "")))
        _log(
            "load", self.backend,
            f"scope={scope_id} task_id={record.get('task_id')} "
            f"candidates={len(candidates)}",
        )
        return record


def get_state_store() -> StateStore:
    if config.STATE_BACKEND == "local":
        return LocalStateStore()
    return PowerContextStateStore()


def build_record(
    *,
    task_id: str,
    task: str,
    status: str,
    development: Dict[str, Any],
    target: Dict[str, Any],
    regression: Dict[str, Any],
    changed_files: List[str],
    context: Dict[str, Any],
    done: List[str] | None = None,
    todo: List[str] | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "task_id": task_id,
        "task": task,
        "status": status,
        "updated_at": _now(),
        "changed_files": changed_files,
        "done": done or [],
        "todo": todo or [],
        "attempts": [
            {
                "attempt": a["attempt"],
                "provider": a.get("provider"),
                "diff_sha1": a.get("diff_sha1"),
                "applied": a.get("applied"),
                "error": a.get("error"),
                "target_passed": bool(a.get("target") and a["target"]["passed"]),
            }
            for a in development.get("attempts", [])
        ],
        "target_tests": {
            "passed": target.get("passed"),
            "counts": target.get("counts"),
            "log": target.get("log"),
        },
        "regression_tests": {
            "passed": regression.get("passed"),
            "counts": regression.get("counts"),
            "log": regression.get("log"),
        },
        "context_sources": context.get("sources", []),
        "verification": {
            "target_tests": target.get("passed"),
            "target_counts": target.get("counts"),
            "regression_tests": regression.get("passed"),
            "regression_counts": regression.get("counts"),
        },
    }
    if extra:
        record.update(extra)
    return record
