"""Build a development context bundle for a task from stored engineering data."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .db import DocStore

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_ASCII = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def extract_keywords(task: str) -> List[str]:
    words = {w.lower() for w in _ASCII.findall(task)}
    for run in _CJK.findall(task):
        for i in range(len(run) - 1):
            words.add(run[i : i + 2])
    # Prefer longer tokens first, then keep a bounded set.
    ordered = sorted(words, key=lambda w: (-len(w), w))
    return ordered[:60]


def _pick(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    # Retrieval ranking comes from the store; only demote whole-module chunks so
    # that concrete functions/classes win when both match the task.
    ordered = [r for r in rows if r.get("symbol") != "<module>"]
    ordered += [r for r in rows if r.get("symbol") == "<module>"]
    picked, seen, paths = [], set(), set()
    for row in ordered:
        key = (row["path"], row.get("symbol"), row.get("req_id"), row.get("lineno"))
        if key in seen:
            continue
        if row.get("symbol") == "<module>" and row["path"] in paths:
            continue
        seen.add(key)
        paths.add(row["path"])
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def _slim(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "path": row["path"], "req_id": row.get("req_id"),
        "symbol": row.get("symbol"), "lineno": row.get("lineno"),
        "text": row["text"],
    }


def build_context(
    store: DocStore, task: str, history: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    keywords = extract_keywords(task)
    specs = _pick(store.query("spec", keywords), 6)
    code = _pick(store.query("code", keywords), 6)
    tests = _pick(store.query("test", keywords), 6)

    bundle: Dict[str, Any] = {
        "task": task,
        "keywords": keywords,
        "specs": [_slim(r) for r in specs],
        "code": [_slim(r) for r in code],
        "tests": [_slim(r) for r in tests],
    }
    if history:
        bundle["history"] = {
            key: history.get(key)
            for key in (
                "task_id", "status", "updated_at", "changed_files",
                "done", "todo", "verification",
            )
        }
    bundle["sources"] = [
        {"type": "spec", "path": s["path"], "ref": s.get("req_id") or s["path"]}
        for s in bundle["specs"]
    ] + [
        {"type": "code", "path": c["path"], "ref": f"{c['path']}#L{c['lineno']}:{c['symbol']}"}
        for c in bundle["code"]
    ] + [
        {"type": "test", "path": t["path"], "ref": f"{t['path']}::{t['symbol']}"}
        for t in bundle["tests"]
    ]
    return bundle


def render_context_text(bundle: Dict[str, Any]) -> str:
    lines: List[str] = ["# 开发上下文", "", "## 任务", bundle["task"], ""]
    history = bundle.get("history")
    if history:
        lines.append("## 上一轮任务进展（来自状态存储）")
        lines.append(f"- 任务：{history.get('task_id')}（{history.get('status')}）")
        lines.append(f"- 更新时间：{history.get('updated_at')}")
        lines.append(f"- 变更文件：{', '.join(history.get('changed_files') or []) or '-'}")
        for label, key in (("已完成", "done"), ("待办", "todo")):
            items = history.get(key) or []
            if items:
                lines.append(f"- {label}：")
                lines.extend(f"  - {item}" for item in items)
        verification = history.get("verification") or {}
        if verification:
            lines.append(f"- 已有验证：{verification}")
        lines.append("")
    lines.append("## 适用规格")
    for s in bundle["specs"]:
        lines.append(f"### {s.get('req_id') or s['path']}  ({s['path']})")
        lines.append(s["text"])
        lines.append("")
    lines.append("## 相关代码")
    for c in bundle["code"]:
        lines.append(f"### {c['path']}#L{c['lineno']} {c.get('symbol')}")
        lines.append("```python")
        lines.append(c["text"])
        lines.append("```")
        lines.append("")
    lines.append("## 相关测试")
    for t in bundle["tests"]:
        lines.append(f"### {t['path']}::{t.get('symbol')}")
        lines.append("```python")
        lines.append(t["text"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
