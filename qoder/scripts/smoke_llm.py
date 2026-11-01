"""D1 验收 2：StepFun 抽取跑通。读取样例纪要，输出结构化条目。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import SAMPLES_DIR, STEP_MODEL  # noqa: E402
from backend.extract import extract_items  # noqa: E402


def main() -> None:
    path = SAMPLES_DIR / "meeting-01.md"
    text = path.read_text(encoding="utf-8")
    print(f"model={STEP_MODEL} source={path.name} chars={len(text)}")

    items = extract_items(text, project="Aurora", source=path.name)
    print(f"\n抽到 {len(items)} 条：\n")
    for index, item in enumerate(items, start=1):
        print(f"{index}. [{item.kind}] {item.title}")
        print(f"   owner={item.owner or '-'} due={item.due or '-'} confidence={item.confidence:.2f}")
        print(f"   keywords={item.keywords}")
        print(f"   detail={item.detail}")

    print("\n[OK] StepFun 抽取链路跑通")


if __name__ == "__main__":
    main()
