"""建 PowerContext Scope，把纪要存成 Source，把长期约束写成 Memory，再验证召回。

用法：
    python scripts/setup_powercontext.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import handoff, ledger, powercontext as pc  # noqa: E402
from backend.config import SAMPLES_DIR  # noqa: E402

PROJECT = "Aurora"
SCOPE_TITLE = "Aurora 登录改造 · 接力棒演示 Scope"
SCOPE_SUMMARY = "存放三次会议记录、生效中的决定与约束，供交接时召回上下文"
IDEMPOTENCY_KEY = "relay-aurora-demo-v1"


def ensure_scope() -> str:
    result = pc.create_scope(
        title=SCOPE_TITLE, summary=SCOPE_SUMMARY, idempotency_key=IDEMPOTENCY_KEY
    )
    scope_id = result.get("scope_id") or result.get("scope", {}).get("scope_id") or ""
    if not scope_id:
        raise RuntimeError(f"建 Scope 没拿到 scope_id：{result}")
    pc.save_scope(scope_id)
    print(f"[1/4] Scope 已建好并写入 {pc.SCOPE_FILE}：{scope_id}")
    return scope_id


def capture_samples() -> None:
    for path in sorted(SAMPLES_DIR.glob("meeting-*.md")):
        source_id = f"relay-{path.stem}"
        pc.capture_source(
            source_id,
            path.read_text(encoding="utf-8"),
            metadata={"project": PROJECT, "file": path.name},
        )
        print(f"      Source {source_id} ← {path.name}")


def remember_decisions() -> None:
    entries = ledger.load(project=PROJECT)
    decisions = [e for e in entries if e.kind in ("decision", "risk")]
    for entry in decisions:
        pc.remember(
            entry.kind,
            f"{entry.title}：{entry.detail}",
            reason=f"来自 {entry.source}，接力棒台账里仍然生效",
        )
        print(f"      Memory [{entry.kind}] {entry.title}")


def check_recall() -> None:
    query = "旧接口能不能下线？灰度放量到什么程度了？"
    memory = pc.search_memory(query, limit=5)
    hits = memory.get("hits") or []
    print(f"\n[4/4] memory/search 召回模式={memory.get('mode')}，命中 {len(hits)} 条")
    for hit in hits[:5]:
        text = hit.get("memory", {}).get("text", "")
        print(f"      - {text[:70]}")

    context = pc.prepare_context(query, max_bytes=4000)
    content = context.get("content") or context.get("context") or ""
    used = context.get("used_bytes") or context.get("byte_count") or len(str(content).encode())
    print(f"\ncontext/prepare 产出 {used} 字节：")
    print(str(content)[:1500])


def main() -> None:
    if not pc.is_available():
        print(f"[X] PowerContext Server 没在 {pc.POWERCONTEXT_BASE_URL} 监听。")
        print("    WSL 里先起服务：cd ~/pc-run && ~/pc-venv/bin/powercontext server run")
        sys.exit(1)

    print(f"[1/4] 连接 {pc.POWERCONTEXT_BASE_URL} 正常")
    ensure_scope()

    print("[2/4] 会议纪要落 Source：")
    capture_samples()

    print("[3/4] 台账里的决定与约束落 Memory：")
    remember_decisions()

    check_recall()

    entries = ledger.load(project=PROJECT)
    sections = handoff.card_sections(entries, as_of="2026-09-29")
    print(f"\n台账共 {len(entries)} 条，其中决定/风险 {len(sections['decisions'])} 条已进 Memory")
    print("[OK] PowerContext 链路跑通")


if __name__ == "__main__":
    main()
