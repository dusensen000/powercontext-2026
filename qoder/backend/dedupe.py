from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import store
from .config import DEDUPE_THRESHOLD
from .schema import WorkItem


@dataclass
class Match:
    item: WorkItem
    matched_id: str | None
    matched_title: str
    distance: float | None
    reason: str

    @property
    def is_duplicate(self) -> bool:
        return self.matched_id is not None


def pick_keyword(item: WorkItem) -> str | None:
    """从 keywords 里挑最长的一个做全文检索词；$contains 需要短词才命中。"""
    candidates = [part.strip() for part in item.keywords.split(",") if part.strip()]
    candidates = [part for part in candidates if len(part) >= 2]
    if not candidates:
        return None
    return max(candidates, key=len)


def find_duplicate(item: WorkItem, *, n_results: int = 3) -> Match:
    """混合检索召回候选，再用余弦距离精确判定是否为同一件事。

    hybrid_search 返回的是 RRF 融合分，不能直接当相似度阈值用，
    所以候选拿到后统一用 embed_pair 复核距离。
    """
    results = store.hybrid_find(
        item.document(),
        keyword=pick_keyword(item),
        project=item.project,
        n_results=n_results,
    )
    ids = _first(results.get("ids"))
    documents = _first(results.get("documents"))
    metadatas = _first(results.get("metadatas"))
    if not ids:
        return Match(item, None, "", None, "台账里没有相似条目，按新条目入库")

    best: tuple[str, str, dict[str, Any], float] | None = None
    for candidate_id, document, metadata in zip(ids, documents, metadatas):
        distance = store.embed_pair(item.document(), document)
        if best is None or distance < best[3]:
            best = (candidate_id, document, metadata, distance)

    assert best is not None
    candidate_id, _, metadata, distance = best
    title = str(metadata.get("title", ""))
    if distance <= DEDUPE_THRESHOLD:
        return Match(
            item,
            candidate_id,
            title,
            distance,
            f"与已有条目「{title}」余弦距离 {distance:.3f} ≤ 阈值 {DEDUPE_THRESHOLD}，判定为同一件事的更新",
        )
    return Match(
        item,
        None,
        title,
        distance,
        f"最接近的条目「{title}」距离 {distance:.3f} > 阈值 {DEDUPE_THRESHOLD}，按新条目入库",
    )


def _first(value: Any) -> list[Any]:
    if not value:
        return []
    return value[0] if isinstance(value[0], list) else value
