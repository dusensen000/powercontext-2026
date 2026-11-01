"""台账读取、对账（超期/失联）与状态更新。"""
from __future__ import annotations

from typing import Any

from . import store
from .schema import OPEN_STATUSES, WorkItem


class Entry:
    __slots__ = ("id", "kind", "title", "detail", "owner", "due", "status", "source")

    def __init__(
        self,
        item_id: str,
        kind: str,
        title: str,
        detail: str,
        owner: str,
        due: str,
        status: str,
        source: str,
    ) -> None:
        self.id = item_id
        self.kind = kind
        self.title = title
        self.detail = detail
        self.owner = owner
        self.due = due
        self.status = status
        self.source = source

    @classmethod
    def from_record(cls, item_id: str, meta: dict[str, Any]) -> "Entry":
        return cls(
            item_id,
            str(meta.get("kind", "")),
            str(meta.get("title", "")),
            str(meta.get("detail", "")),
            str(meta.get("owner") or ""),
            str(meta.get("due") or ""),
            str(meta.get("status") or "open"),
            str(meta.get("source") or ""),
        )

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def label(self) -> str:
        owner = self.owner or "无人认领"
        due = f"｜原定 {self.due}" if self.due else ""
        return f"{self.title}｜{owner}{due}"


def load(project: str | None = None, statuses: list[str] | None = None) -> list[Entry]:
    result = store.list_items(project=project, statuses=statuses)
    ids = result.get("ids") or []
    metadatas = result.get("metadatas") or []
    return [Entry.from_record(item_id, meta) for item_id, meta in zip(ids, metadatas)]


def overdue(entries: list[Entry], as_of: str) -> list[Entry]:
    return [entry for entry in entries if entry.is_open and entry.due and entry.due < as_of]


def unassigned(entries: list[Entry]) -> list[Entry]:
    return [entry for entry in entries if entry.is_open and not entry.owner]


def set_status(item_id: str, status: str) -> None:
    found = store.get_item(item_id)
    if found is None:
        raise KeyError(f"台账里没有 {item_id}")
    item = WorkItem.from_metadata(found["metadata"], found["id"])
    item.status = status
    store.update_item(item)


def summary(entries: list[Entry], as_of: str) -> dict[str, int]:
    return {
        "total": len(entries),
        "open": sum(1 for entry in entries if entry.is_open),
        "done": sum(1 for entry in entries if entry.status == "done"),
        "overdue": len(overdue(entries, as_of)),
        "unassigned": len(unassigned(entries)),
    }
