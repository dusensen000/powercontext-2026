"""验证 embedding：模型能否从镜像下载、维度、归一化情况、中文近义句距离。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.embedding import BgeEmbeddingFunction  # noqa: E402
from backend.store import cosine_distance  # noqa: E402

PAIRS = [
    ("数据库连接池在高峰期被打满", "数据库压力太大导致连接不够用", "同义改写，应该很近"),
    ("灰度发布先放百分之五的流量", "登录页改版设计稿交付", "无关，应该很远"),
    ("旧 auth 接口不能下线", "移动端仍在使用旧接口", "相关，应该较近"),
]


def main() -> None:
    function = BgeEmbeddingFunction()
    vectors = function([text for left, right, _ in PAIRS for text in (left, right)])
    print(f"model={function.model_name} dimension={function.dimension} count={len(vectors)}")

    for index, (left, right, note) in enumerate(PAIRS):
        a, b = vectors[index * 2], vectors[index * 2 + 1]
        norm = sum(x * x for x in a) ** 0.5
        print(f"\n{note}")
        print(f"  A: {left}")
        print(f"  B: {right}")
        print(f"  余弦距离={cosine_distance(a, b):.4f}  向量模长={norm:.4f}")

    print("\n[OK] embedding 可用")


if __name__ == "__main__":
    main()
