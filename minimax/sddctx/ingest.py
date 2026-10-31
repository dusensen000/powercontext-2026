"""Ingest engineering material (specs, code, tests) into the document store."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List

from .db import DocStore


def _hash(*parts: Any) -> str:
    return hashlib.sha1("||".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(sample: Path, path: Path) -> str:
    return path.relative_to(sample).as_posix()


def parse_specs(sample: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for path in sorted((sample / "specs").glob("*.md")):
        rel = _rel(sample, path)
        text = _read(path)
        # Split on level-2 headings; keep each requirement as its own chunk.
        parts = re.split(r"(?m)^(?=##\s+)", text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            m = re.search(r"REQ-\d+", part)
            docs.append(
                {
                    "path": rel,
                    "kind": "spec",
                    "req_id": m.group(0) if m else None,
                    "symbol": None,
                    "lineno": None,
                    "text": part,
                    "hash": _hash(rel, part),
                }
            )
    return docs


def _ast_docs(sample: Path, path: Path, kind: str, predicate) -> List[Dict[str, Any]]:
    rel = _rel(sample, path)
    source = _read(path)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    docs: List[Dict[str, Any]] = [
        {
            "path": rel, "kind": kind, "req_id": None, "symbol": "<module>",
            "lineno": 1, "text": source, "hash": _hash(rel, source),
        }
    ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and predicate(node):
            end = getattr(node, "end_lineno", node.lineno)
            start = node.lineno
            if node.decorator_list:
                start = min(start, node.decorator_list[0].lineno)
            segment = "\n".join(lines[start - 1 : end])
            docs.append(
                {
                    "path": rel, "kind": kind, "req_id": None, "symbol": node.name,
                    "lineno": start, "text": segment, "hash": _hash(rel, node.name, segment),
                }
            )
    return docs


def parse_code(sample: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for path in sorted((sample / "src").rglob("*.py")):
        docs.extend(_ast_docs(sample, path, "code", lambda n: True))
    return docs


def parse_tests(sample: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for path in sorted((sample / "tests").rglob("test_*.py")):
        docs.extend(
            _ast_docs(sample, path, "test", lambda n: n.name.startswith("test_"))
        )
    return docs


def collect(sample: Path) -> List[Dict[str, Any]]:
    return parse_specs(sample) + parse_code(sample) + parse_tests(sample)


def ingest(store: DocStore, sample: Path) -> Dict[str, int]:
    docs = collect(sample)
    store.reset()
    store.insert_many(docs)
    by_kind: Dict[str, int] = {}
    for d in docs:
        by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1
    by_kind["total"] = len(docs)
    return by_kind
