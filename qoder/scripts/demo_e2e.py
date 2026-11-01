"""端到端演示：三份纪要依次入库，seekdb 去重合并，输出台账、对账结果和交接卡。

用法：
    python scripts/demo_e2e.py            # 增量入库
    python scripts/demo_e2e.py --reset    # 先清空本地 seekdb 数据再跑
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import handoff, ledger, powercontext as pc, store  # noqa: E402
from backend.config import SAMPLES_DIR, SEEKDB_PATH  # noqa: E402
from backend.dedupe import find_duplicate  # noqa: E402
from backend.extract import extract_items  # noqa: E402
from backend.schema import WorkItem  # noqa: E402

PROJECT = "Aurora"
DISPLAY = "Aurora 登录改造"
OBJECTIVE = "把登录接口 P95 从 1.2s 降到 400ms 以内，灰度验证后全量发布"
AS_OF = "2026-09-29"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "out"


def merge(existing: WorkItem, incoming: WorkItem) -> WorkItem:
    existing.detail = incoming.detail
    existing.source = f"{existing.source} → {incoming.source}"
    existing.owner = incoming.owner or existing.owner
    existing.due = incoming.due or existing.due
    existing.keywords = incoming.keywords or existing.keywords
    existing.confidence = max(existing.confidence, incoming.confidence)
    if incoming.status == "done":
        existing.status = "done"
    elif existing.status == "open" and incoming.status != "open":
        existing.status = incoming.status
    return existing


def ingest(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    items = extract_items(text, project=PROJECT, source=path.name)
    print(f"\n{'=' * 72}\n{path.name} → 抽到 {len(items)} 条\n{'=' * 72}")
    for item in items:
        match = find_duplicate(item)
        if match.is_duplicate:
            found = store.get_item(match.matched_id)
            if found is None:
                store.add_items([item])
                print(f"  [新增] {item.title}（合并目标已不存在）")
                continue
            merged = merge(WorkItem.from_metadata(found["metadata"], found["id"]), item)
            store.update_item(merged)
            print(f"  [合并] {item.title} → {merged.title}｜{merged.status}")
            print(f"         {match.reason}")
        else:
            store.add_items([item])
            print(f"  [新增] {item.title}｜{item.status}")
            print(f"         {match.reason}")


def sync_to_powercontext(sections: dict[str, list[str]]) -> None:
    """把工作契约 → Prepared Handoff → 确认回执 → 任务结果四步落到 PowerContext。"""
    if not pc.is_available():
        print("\n[skip] PowerContext Server 不在线，跳过交接四步（起服务后重跑即可）")
        return

    # 同一 source_id 改写内容会 409，每次演示用独立的一轮 id
    run = uuid.uuid4().hex[:8]

    contract = handoff.create_contract(
        source_id=f"relay-contract-{run}",
        objective=OBJECTIVE,
        in_scope=["登录接口性能优化", "灰度放量与回滚阈值", "新旧接口并存"],
        completion_criteria=["P95 ≤ 400ms", "全量发布后旧 auth 接口仍可用"],
        facts=sections["decisions"],
        open_questions=sections["questions"],
    )
    print(f"[PowerContext] 工作契约已建：position={contract.get('position')}")

    prepared = handoff.prepare_handoff(
        source_id=f"relay-handoff-{run}",
        objective=OBJECTIVE,
        state=sections["open"] + sections["overdue"],
        next_action=sections["open"][0] if sections["open"] else "确认剩余事项归属",
        omissions=sections["risks"],
    )
    print(f"[PowerContext] Prepared Handoff 已生成：position={prepared.get('boundary', {}).get('position')}")

    ack = handoff.acknowledge_handoff(
        source_id=f"relay-ack-{run}",
        receiver="赵磊",
        handoff_payload=prepared["handoff"],
        receiver_checks={
            "live_state": "confirmed",
            "capability": "confirmed",
            "authorization": "confirmed",
        },
        message="已核对超期与未认领事项，接手后先跑全量回归",
    )
    print(
        "[PowerContext] 接手回执已记录："
        f"evidence={ack.get('resolution', {}).get('evidence_checks', [{}])[0].get('status')}"
    )

    outcome = handoff.record_outcome(
        source_id=f"relay-outcome-{run}",
        objective=OBJECTIVE,
        status="partial",
        summary=f"截至 {AS_OF} 完成 {len(sections['done'])} 项，剩余 {len(sections['open'])} 项待接手",
        observations=sections["done"],
        remaining_work=sections["open"],
    )
    print(f"[PowerContext] 任务结果已落库：position={outcome.get('position')}")


def report() -> None:
    entries = ledger.load(project=PROJECT)
    stats = ledger.summary(entries, AS_OF)
    overdue_ids = {entry.id for entry in ledger.overdue(entries, AS_OF)}

    print(f"\n{'=' * 72}")
    print(
        f"台账（截至 {AS_OF}）：共 {stats['total']} 条｜未完成 {stats['open']}｜"
        f"已完成 {stats['done']}｜已超期 {stats['overdue']}｜没人认领 {stats['unassigned']}"
    )
    print("=" * 72)
    for entry in sorted(entries, key=lambda item: (item.kind, item.due or "9999-99-99")):
        flag = "  ← 已超期" if entry.id in overdue_ids else ""
        print(f"  [{entry.kind:8}] {entry.title}｜{entry.owner or '-'}｜{entry.due or '-'}｜{entry.status}{flag}")

    sections = handoff.card_sections(entries, as_of=AS_OF)
    card = handoff.render_card(
        project=DISPLAY,
        objective=OBJECTIVE,
        as_of=AS_OF,
        sections=sections,
        from_person="张伟",
        to_person="赵磊",
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    card_path = OUT_DIR / "handoff-card.md"
    card_path.write_text(card, encoding="utf-8")
    print(f"\n{'=' * 72}\n交接卡已写入 {card_path}\n{'=' * 72}\n")
    print(card)
    sync_to_powercontext(sections)


def main() -> None:
    if "--reset" in sys.argv:
        # SEEKDB_PATH 是嵌入式实例目录，不是单个文件
        shutil.rmtree(SEEKDB_PATH, ignore_errors=True)
        print(f"已清空 {SEEKDB_PATH}")

    for path in sorted(SAMPLES_DIR.glob("meeting-*.md")):
        ingest(path)
    report()
    print("[OK] 端到端链路跑通")


if __name__ == "__main__":
    main()
