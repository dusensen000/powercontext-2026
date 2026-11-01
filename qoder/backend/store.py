from __future__ import annotations

import uuid
from typing import Any

import pyseekdb

from .config import (
    SEEKDB_COLLECTION,
    SEEKDB_DATABASE,
    SEEKDB_HOST,
    SEEKDB_PASSWORD,
    SEEKDB_PATH,
    SEEKDB_PORT,
    SEEKDB_USE_SERVER,
    SEEKDB_USER,
)
from .dbinit import ensure_database
from .embedding import BgeEmbeddingFunction
from .schema import WorkItem

_collection: Any = None
_embedding: BgeEmbeddingFunction | None = None
_INCLUDE = ["documents", "metadatas", "distances"]


def get_embedding() -> BgeEmbeddingFunction:
    global _embedding
    if _embedding is None:
        _embedding = BgeEmbeddingFunction()
    return _embedding


def get_collection(name: str | None = None) -> Any:
    global _collection
    if _collection is None:
        _collection = _build_client().get_or_create_collection(
            name=name or SEEKDB_COLLECTION,
            embedding_function=get_embedding(),
        )
    return _collection


def _build_client() -> Any:
    ensure_database()
    if SEEKDB_USE_SERVER:
        return pyseekdb.Client(
            host=SEEKDB_HOST,
            port=SEEKDB_PORT,
            database=SEEKDB_DATABASE,
            user=SEEKDB_USER,
            password=SEEKDB_PASSWORD,
        )
    return pyseekdb.Client(path=str(SEEKDB_PATH), database=SEEKDB_DATABASE)


def add_items(items: list[WorkItem]) -> list[str]:
    if not items:
        return []
    for item in items:
        if not item.id:
            item.id = uuid.uuid4().hex
    collection = get_collection()
    collection.add(
        ids=[item.id for item in items],
        documents=[item.document() for item in items],
        metadatas=[item.metadata() for item in items],
    )
    collection.refresh_index()
    return [item.id for item in items]


def update_item(item: WorkItem) -> None:
    collection = get_collection()
    collection.update(ids=[item.id], documents=[item.document()], metadatas=[item.metadata()])
    collection.refresh_index()


def hybrid_find(
    text: str,
    *,
    keyword: str | None = None,
    project: str | None = None,
    n_results: int = 5,
) -> dict[str, Any]:
    """全文 + 向量 + 标量过滤，一次调用完成，RRF 融合排序。"""
    window = max(n_results * 4, 20)
    knn: dict[str, Any] = {"query_texts": [text], "n_results": window}
    if project:
        knn["where"] = {"project": project}
    params: dict[str, Any] = {
        "knn": knn,
        "rank": {"rrf": {}},
        "n_results": n_results,
        "include": _INCLUDE,
    }
    if keyword:
        query: dict[str, Any] = {
            "where_document": {"$contains": keyword},
            "n_results": window,
        }
        if project:
            query["where"] = {"project": project}
        params["query"] = query
    return get_collection().hybrid_search(**params)


def semantic_find(
    text: str,
    *,
    project: str | None = None,
    n_results: int = 5,
) -> dict[str, Any]:
    return get_collection().query(
        query_texts=[text],
        where={"project": project} if project else None,
        n_results=n_results,
        include=_INCLUDE,
    )


def keyword_find(keyword: str, *, project: str | None = None, limit: int = 20) -> dict[str, Any]:
    return get_collection().get(
        where={"project": project} if project else None,
        where_document={"$contains": keyword},
        limit=limit,
        include=["documents", "metadatas"],
    )


def get_item(item_id: str) -> dict[str, Any] | None:
    result = get_collection().get(ids=[item_id], include=["documents", "metadatas"])
    ids = result.get("ids") or []
    if not ids:
        return None
    metadatas = result.get("metadatas") or [{}]
    documents = result.get("documents") or [""]
    return {"id": ids[0], "metadata": metadatas[0], "document": documents[0]}


def list_items(
    *,
    project: str | None = None,
    statuses: list[str] | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    conditions: list[dict[str, Any]] = []
    if project:
        conditions.append({"project": project})
    if statuses:
        conditions.append({"status": {"$in": statuses}})
    if len(conditions) > 1:
        where: dict[str, Any] | None = {"$and": conditions}
    elif conditions:
        where = conditions[0]
    else:
        where = None
    return get_collection().get(where=where, limit=limit, include=["documents", "metadatas"])


def embed_pair(left: str, right: str) -> float:
    """返回余弦距离（1 - 余弦相似度）。不假设 embedding 已归一化，
    用于给混合检索召回的候选做精确复核。"""
    vectors = get_embedding()([left, right])
    return cosine_distance(vectors[0], vectors[1])


def cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)
