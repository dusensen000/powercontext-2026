"""真实台账上的三路检索对比（smoke_seekdb.py 用的是 4 条固定样本，这里打的是去重后的台账）。

同时把结果写进 data/out/search-check.txt，展示站上的三路对比数字就取自这里。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import store  # noqa: E402
from backend.config import PROJECT_ROOT  # noqa: E402

PROJECT = "Aurora"
QUERY = "数据库压力太大怎么办"
KEYWORD = "连接池"


def rows(result: dict[str, Any], *, with_score: bool) -> list[str]:
    documents = result.get("documents") or []
    scores = result.get("distances") or result.get("scores") or []
    if documents and isinstance(documents[0], list):
        documents = documents[0]
        scores = scores[0] if scores else []
    lines = []
    for index, document in enumerate(documents):
        title = (document or "").splitlines()[0]
        if with_score and index < len(scores) and scores[index] is not None:
            lines.append(f"  {index + 1}. {title}  {scores[index]:.4f}")
        else:
            lines.append(f"  {index + 1}. {title}")
    return lines


def main() -> int:
    total = len(store.list_items(project=PROJECT).get("ids") or [])
    blocks = [f"台账条数：{total}（项目 {PROJECT}）"]
    blocks.append(f"--- 只关键词「{KEYWORD}」 ---")
    blocks += rows(store.keyword_find(KEYWORD, project=PROJECT, limit=5), with_score=False)
    blocks.append(f"--- 只语义「{QUERY}」 ---")
    blocks += rows(store.semantic_find(QUERY, project=PROJECT, n_results=5), with_score=True)
    blocks.append(f"--- 混合检索（全文「{KEYWORD}」+ 语义「{QUERY}」+ RRF） ---")
    blocks += rows(store.hybrid_find(QUERY, keyword=KEYWORD, project=PROJECT, n_results=5), with_score=True)

    text = "\n".join(blocks)
    out = PROJECT_ROOT / "data" / "out" / "search-check.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\n[OK] 已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
