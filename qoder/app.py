"""接力棒 Relay 的本地界面。

运行：
    bash run.sh app.py --ui
"""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st

from backend import handoff, ledger, powercontext as pc, store
from backend.config import DEDUPE_THRESHOLD, SEEKDB_DATABASE, SEEKDB_PATH
from backend.dedupe import find_duplicate
from backend.extract import extract_items, meeting_date
from backend.schema import ALL_STATUSES, WorkItem

KIND_LABEL = {"decision": "决定", "action": "行动项", "risk": "风险", "question": "待确认"}
STATUS_LABEL = {"open": "待办", "in_progress": "进行中", "done": "已完成", "blocked": "受阻"}

st.set_page_config(page_title="接力棒 Relay", page_icon="🏃", layout="wide")


@st.cache_resource
def _boot() -> dict[str, Any]:
    return {"count": store.get_collection().count()}


def sidebar() -> tuple[str, str]:
    st.sidebar.title("接力棒 Relay")
    project = st.sidebar.text_input("项目代号", value="Aurora")
    as_of = st.sidebar.date_input("对账基准日", value=date.today())
    counts = _boot()
    st.sidebar.caption(
        f"seekdb：`{SEEKDB_DATABASE}` @ `{SEEKDB_PATH}`｜当前 {counts['count']} 条\n\n"
        f"去重阈值（余弦距离）：{DEDUPE_THRESHOLD}\n\n"
        f"PowerContext：{'在线' if pc.is_available() else '未启动（交接四步会被跳过）'}"
    )
    return project, as_of.isoformat()


def ingest_tab(project: str) -> None:
    st.subheader("1. 粘贴纪要")
    text = st.text_area("会议纪要 / 聊天记录原文", height=260, key="raw")
    col_a, col_b = st.columns(2)
    extract = col_a.button("抽取条目", type="primary", disabled=not text.strip())
    clear = col_b.button("清空")

    if clear:
        st.session_state.pop("draft", None)
        st.session_state.pop("raw", None)
        st.rerun()

    if extract:
        with st.spinner("StepFun 抽取中"):
            st.session_state["draft"] = extract_items(
                text, project=project, source=f"手动录入 {date.today().isoformat()}"
            )

    result = st.session_state.pop("ingest_result", "")
    if result:
        st.success(result)

    draft = st.session_state.get("draft") or []
    if not draft:
        st.info("抽取后这里会出现候选条目，以及每条与台账里最相似条目的距离。")
        return

    st.caption(f"记录日期识别为：{meeting_date(text) or '未知'}")
    rows = []
    for item in draft:
        match = find_duplicate(item)
        rows.append(
            {
                "类型": KIND_LABEL.get(item.kind, item.kind),
                "标题": item.title,
                "负责人": item.owner or "-",
                "截止": item.due or "-",
                "状态": STATUS_LABEL.get(item.status, item.status),
                "判定": "重复 → 合并" if match.is_duplicate else "新条目",
                "最近距离": "-" if match.distance is None else f"{match.distance:.3f}",
                "匹配到": match.matched_title or "-",
            }
        )
    st.dataframe(rows, width="stretch")

    if st.button("确认入库", type="primary"):
        added = merged = 0
        for item in draft:
            match = find_duplicate(item)
            if match.is_duplicate:
                found = store.get_item(match.matched_id)
                if found is not None:
                    store.update_item(_merge(WorkItem.from_metadata(found["metadata"], found["id"]), item))
                    merged += 1
                    continue
            store.add_items([item])
            added += 1
        st.session_state.pop("draft", None)
        st.session_state["ingest_result"] = f"新增 {added} 条，合并 {merged} 条"
        st.cache_resource.clear()
        st.rerun()


def _merge(existing: WorkItem, incoming: WorkItem) -> WorkItem:
    existing.detail = incoming.detail
    existing.source = f"{existing.source} → {incoming.source}"
    existing.owner = incoming.owner or existing.owner
    existing.due = incoming.due or existing.due
    if incoming.status == "done":
        existing.status = "done"
    elif incoming.status != "open" and existing.status == "open":
        existing.status = incoming.status
    return existing


def ledger_tab(project: str, as_of: str) -> None:
    st.subheader("2. 台账与对账")
    entries = ledger.load(project=project)
    if not entries:
        st.info("台账是空的，先去「粘贴纪要」录一条。")
        return
    stats = ledger.summary(entries, as_of)
    st.markdown(
        f"**{stats['total']}** 条 ｜ **{stats['open']}** 未完成 ｜ **{stats['done']}** 已完成 "
        f"｜ 超期 **{stats['overdue']}** ｜ 无人认领 **{stats['unassigned']}**"
    )

    overdue_ids = {entry.id for entry in ledger.overdue(entries, as_of)}
    unassigned_ids = {entry.id for entry in ledger.unassigned(entries)}
    only_open = st.checkbox("只看未完成", value=True)
    show = [entry for entry in entries if (not only_open or entry.is_open)]

    for entry in show:
        flags = []
        if entry.id in overdue_ids:
            flags.append("已超期")
        if entry.id in unassigned_ids:
            flags.append("无人认领")
        cols = st.columns([3, 1.2, 1, 1, 1.4])
        cols[0].markdown(f"**{entry.title}**  \n{entry.detail[:90]}")
        cols[1].write(f"{KIND_LABEL.get(entry.kind, entry.kind)}｜{entry.owner or '无人'}")
        cols[2].write(entry.due or "-")
        cols[3].markdown("**" + " ".join(flags) + "**" if flags else "")
        cols[4].selectbox(
            "状态",
            options=list(ALL_STATUSES),
            index=list(ALL_STATUSES).index(entry.status),
            key=f"st_{entry.id}",
            format_func=lambda value: STATUS_LABEL.get(value, value),
            label_visibility="collapsed",
        )
        if st.button("改状态", key=f"btn_{entry.id}"):
            ledger.set_status(entry.id, st.session_state[f"st_{entry.id}"])
            st.cache_resource.clear()
            st.rerun()


def search_tab(project: str) -> None:
    st.subheader("3. 检索验证（seekdb 三路对比）")
    query = st.text_input("想查的事", value="数据库压力太大怎么办")
    keyword = st.text_input("关键词（全文匹配）", value="连接池")
    if not query:
        return
    left, right, top = st.columns(3)
    with left:
        st.markdown("**只关键词**")
        for row in _rows(store.keyword_find(keyword, project=project, limit=5)):
            st.write(row)
    with right:
        st.markdown("**只语义**")
        for row in _rows(store.semantic_find(query, project=project, n_results=5), with_distance=True):
            st.write(row)
    with top:
        st.markdown("**混合（RRF）**")
        for row in _rows(store.hybrid_find(query, keyword=keyword, project=project, n_results=5), with_distance=True):
            st.write(row)
        st.caption("混合检索返回的是 RRF 融合分，只用于排序；是否重复由本地 embedding 的余弦距离判定。")


def _rows(result: dict[str, Any], *, with_distance: bool = False) -> list[str]:
    documents = result.get("documents") or []
    distances = result.get("distances") or []
    flat = isinstance(documents, list) and documents and isinstance(documents[0], list)
    if flat:
        documents = documents[0]
        distances = distances[0] if distances else []
    lines = []
    for index, document in enumerate(documents):
        title = (document or "").splitlines()[0]
        if with_distance and index < len(distances) and distances[index] is not None:
            lines.append(f"{index + 1}. {title}（{distances[index]:.4f}）")
        else:
            lines.append(f"{index + 1}. {title}")
    return lines


def handoff_tab(project: str, as_of: str) -> None:
    st.subheader("4. 交接")
    entries = ledger.load(project=project)
    if not entries:
        st.info("台账为空，先生成条目。")
        return
    objective = st.text_input("项目目标", value="", key="objective")
    from_person = st.text_input("交出的人", value="张伟")
    to_person = st.text_input("接手的人", value="赵磊")

    sections = handoff.card_sections(entries, as_of=as_of)
    card = handoff.render_card(
        project=project,
        objective=objective or "(填写项目目标)",
        as_of=as_of,
        sections=sections,
        from_person=from_person,
        to_person=to_person,
    )
    st.session_state["card"] = card
    st.markdown(card)

    if st.button("写入 PowerContext（契约 → 交接 → 回执 → 结果）", type="primary"):
        if not pc.is_available():
            st.error("PowerContext Server 不在线。WSL 里先跑 ~/pc-venv/bin/powercontext server run")
            return
        run = uuid.uuid4().hex[:8]
        try:
            with st.spinner("落 PowerContext"):
                handoff.create_contract(
                    source_id=f"relay-contract-{run}",
                    objective=objective or "(未填写)",
                    in_scope=[line for line in sections["open"]][:8],
                    completion_criteria=[line for line in sections["open"]][:3],
                    facts=sections["decisions"],
                    open_questions=sections["questions"],
                )
                prepared = handoff.prepare_handoff(
                    source_id=f"relay-handoff-{run}",
                    objective=objective or "(未填写)",
                    state=sections["open"] + sections["overdue"],
                    next_action=sections["overdue"][0] if sections["overdue"] else (
                        sections["open"][0] if sections["open"] else "确认剩余事项归属"
                    ),
                    omissions=sections["risks"],
                )
                handoff.acknowledge_handoff(
                    source_id=f"relay-ack-{run}",
                    receiver=to_person,
                    handoff_payload=prepared["handoff"],
                    receiver_checks={
                        "live_state": "confirmed",
                        "capability": "confirmed",
                        "authorization": "confirmed",
                    },
                    message="接手前已核对台账与超期项",
                )
                handoff.record_outcome(
                    source_id=f"relay-outcome-{run}",
                    objective=objective or "(未填写)",
                    status="partial",
                    summary=f"截至 {as_of} 仍有 {len(sections['open'])} 项未完成",
                    observations=sections["done"] or ["（本阶段没有已完成项）"],
                    remaining_work=sections["open"],
                )
            st.success("四步已写入 PowerContext Scope")
        except Exception as error:  # noqa: BLE001 - 界面上要看到原始错误
            st.error(f"写入失败：{error}")

    context = pc.prepare_context("这个项目现在什么状态？有什么约束？") if pc.is_available() else None
    if context:
        with st.expander("PowerContext 为该交接召回的上下文"):
            st.text(str(context.get("content", ""))[:2000])


def main() -> None:
    project, as_of = sidebar()
    tabs = st.tabs(["录入", "台账与对账", "检索验证", "交接"])
    with tabs[0]:
        ingest_tab(project)
    with tabs[1]:
        ledger_tab(project, as_of)
    with tabs[2]:
        search_tab(project)
    with tabs[3]:
        handoff_tab(project, as_of)

    st.caption(f"数据目录：`{SEEKDB_PATH}`｜本次运行 {Path(__file__).name}")


if __name__ == "__main__":
    main()
