"""D1 验收 1：seekdb 跑通，并对比关键词 / 语义 / 混合三种检索。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.embedding import BgeEmbeddingFunction  # noqa: E402
from backend.store import _build_client  # noqa: E402

COLLECTION = "smoke_items"

ITEMS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("s1", "登录接口 P95 降到 400ms", "9 月底把登录接口 P95 从 1.2s 降到 400ms 以内",
     {"project": "Aurora", "kind": "decision", "owner": "张伟", "status": "open", "keywords": "登录接口,P95"}),
    ("s2", "灰度先放 5% 流量", "决定采用灰度发布，先放 5% 流量，观察三天没有异常再扩大到 20%",
     {"project": "Aurora", "kind": "decision", "owner": "", "status": "open", "keywords": "灰度,流量"}),
    ("s3", "旧 auth 接口不能下线", "移动端 3.2 版本仍在使用旧的 auth 接口，本次改造不能下线旧接口",
     {"project": "Aurora", "kind": "decision", "owner": "", "status": "open", "keywords": "旧接口,auth"}),
    ("s4", "连接池高峰期打满", "数据库连接池在高峰期被打满，需要 DBA 协助调整参数",
     {"project": "Aurora", "kind": "risk", "owner": "张伟", "status": "open", "keywords": "连接池,DBA"}),
    ("s5", "登录页改版设计稿", "李静负责前端登录页改版，9 月 12 日前交付设计稿",
     {"project": "Aurora", "kind": "action", "owner": "李静", "status": "open", "keywords": "登录页,设计稿"}),
]


def show(label: str, result: dict[str, Any]) -> None:
    print(f"\n--- {label} ---")
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    distances = result.get("distances") or []
    if not ids:
        print("  （无结果）")
        return
    flat = isinstance(ids[0], list)
    id_list = ids[0] if flat else ids
    doc_list = (documents[0] if flat else documents) if documents else []
    dist_list = (distances[0] if flat else distances) if distances else []
    for index, item_id in enumerate(id_list):
        title = (doc_list[index].splitlines() or [""])[0] if index < len(doc_list) else ""
        distance = f"{dist_list[index]:.4f}" if index < len(dist_list) and dist_list[index] is not None else "-"
        print(f"  {index + 1}. [{item_id}] {title}  distance={distance}")


def main() -> None:
    collection = _build_client().get_or_create_collection(
        COLLECTION, embedding_function=BgeEmbeddingFunction()
    )
    print(f"collection={COLLECTION} dimension={collection.dimension} distance={collection.distance}")

    collection.upsert(
        ids=[item[0] for item in ITEMS],
        documents=[f"{item[1]}\n{item[2]}" for item in ITEMS],
        metadatas=[item[3] for item in ITEMS],
    )
    collection.refresh_index()

    show("只关键词：全文匹配「灰度」", collection.get(
        where_document={"$contains": "灰度"},
        include=["documents", "metadatas"],
    ))

    show("只语义：查询「什么时候可以全量放开流量」（原文没有这些词）", collection.query(
        query_texts=["什么时候可以全量放开流量"],
        n_results=3,
        include=["documents", "metadatas", "distances"],
    ))

    show("只标量过滤：owner=张伟", collection.get(
        where={"owner": "张伟"},
        include=["documents", "metadatas"],
    ))

    show("混合检索：全文「连接池」 + 语义「数据库压力太大怎么办」 + RRF", collection.hybrid_search(
        query={"where_document": {"$contains": "连接池"}, "n_results": 10},
        knn={"query_texts": ["数据库压力太大怎么办"], "n_results": 10},
        rank={"rrf": {}},
        n_results=3,
        include=["documents", "metadatas", "distances"],
    ))

    print("\n[OK] seekdb 混合检索链路跑通")


if __name__ == "__main__":
    main()
