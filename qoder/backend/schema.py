from __future__ import annotations

from dataclasses import asdict, dataclass

KINDS = ("decision", "action", "risk", "question")
OPEN_STATUSES = ("open", "in_progress", "blocked")
ALL_STATUSES = ("open", "in_progress", "blocked", "done", "stale")


@dataclass
class WorkItem:
    project: str
    kind: str
    title: str
    detail: str
    owner: str = ""
    due: str = ""
    status: str = "open"
    source: str = ""
    keywords: str = ""
    confidence: float = 0.0
    id: str = ""

    def document(self) -> str:
        return f"{self.title}\n{self.detail}"

    def metadata(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("id")
        return data

    @classmethod
    def from_metadata(cls, metadata: dict[str, object], item_id: str) -> "WorkItem":
        known = {field: metadata.get(field, "") for field in cls.__dataclass_fields__ if field != "id"}
        known["confidence"] = float(known.get("confidence") or 0.0)
        return cls(id=item_id, **known)
