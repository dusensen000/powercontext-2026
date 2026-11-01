"""交接：把当前状态写成 PowerContext 的 Work Contract 与 Prepared Handoff，并渲染成人看的交接卡。

PowerContext 的四步循环：工作契约 → Prepared Handoff → 确认回执 → 任务结果。
这里四步都实现，字段取自运行中服务的 /openapi.json。
"""
from __future__ import annotations

from typing import Any

from . import ledger, powercontext as pc

CONTRACT_SCHEMA = "powercontext.work-contract.v1"
HANDOFF_SCHEMA = "powercontext.current-work-handoff.v1"
OUTCOME_SCHEMA = "powercontext.task-outcome.v1"


def claim(text: str) -> dict[str, Any]:
    """basis=declared：事实来自我们读过的会议记录，而不是 PowerContext 早先返回的引用。"""
    return {"text": text, "basis": "declared", "evidence": []}


def create_contract(
    *,
    source_id: str,
    objective: str,
    in_scope: list[str],
    completion_criteria: list[str],
    facts: list[str],
    open_questions: list[str] | None = None,
    exclusions: list[str] | None = None,
) -> dict[str, Any]:
    return pc.post(
        "/v1/work/contracts/create",
        {
            "scope_id": pc.require_scope(),
            "source_id": source_id,
            "contract": {
                "schema": CONTRACT_SCHEMA,
                "trust": "untrusted_input",
                "objective": objective,
                "facts": [claim(fact) for fact in facts],
                "in_scope": in_scope,
                "exclusions": exclusions or [],
                "completion_criteria": completion_criteria,
                "authorization_notes": [],
                "open_questions": open_questions or [],
            },
        },
    )


def prepare_handoff(
    *,
    source_id: str,
    objective: str,
    state: list[str],
    disposition: str = "continuable",
    next_action: str | None = None,
    omissions: list[str] | None = None,
) -> dict[str, Any]:
    return pc.post(
        "/v1/work/handoffs/prepare-current",
        {
            "scope_id": pc.require_scope(),
            "source_id": source_id,
            "handoff": {
                "schema": HANDOFF_SCHEMA,
                "trust": "untrusted_input",
                "objective": objective,
                "state": [claim(line) for line in state],
                "disposition": disposition,
                "next_action": claim(next_action) if next_action else None,
                "omissions": omissions or [],
            },
        },
    )


def acknowledge_handoff(
    *,
    source_id: str,
    receiver: str,
    handoff_payload: dict[str, Any],
    status: str = "accepted",
    selection: str = "prepared",
    receiver_checks: dict[str, str] | None = None,
    message: str = "",
) -> dict[str, Any]:
    """status=accepted 要求三项自检都是 confirmed，所以自检必须由接手人明确给出。"""
    payload: dict[str, Any] = {
        "scope_id": pc.require_scope(),
        "source_id": source_id,
        "receiver": receiver,
        "status": status,
        "selection": selection,
        "prepared": handoff_payload,
    }
    if receiver_checks:
        payload["receiver_checks"] = receiver_checks
    if message:
        payload["message"] = message
    return pc.post("/v1/work/handoffs/acknowledge", payload)


def record_outcome(
    *,
    source_id: str,
    objective: str,
    summary: str,
    observations: list[str],
    status: str = "partial",
    remaining_work: list[str] | None = None,
    receipt_source_id: str = "",
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "schema": OUTCOME_SCHEMA,
        "trust": "untrusted_observation",
        "objective": objective,
        "status": status,
        "summary": summary,
        "observations": [claim(text) for text in observations],
        "checks": [],
        "produced_artifacts": [],
        "remaining_work": remaining_work or [],
    }
    if receipt_source_id:
        outcome["handoff_receipt_ref"] = {"name": "handoff", "source_id": receipt_source_id}
    return pc.post(
        "/v1/work/outcomes/record",
        {"scope_id": pc.require_scope(), "source_id": source_id, "outcome": outcome},
    )


def card_sections(entries: list[ledger.Entry], *, as_of: str) -> dict[str, list[str]]:
    return {
        "done": [entry.label() for entry in entries if entry.status == "done"],
        "open": [entry.label() for entry in entries if entry.is_open and entry.status != "done"],
        "overdue": [entry.label() for entry in ledger.overdue(entries, as_of)],
        "unassigned": [entry.title for entry in ledger.unassigned(entries)],
        "decisions": [
            f"{entry.title}：{entry.detail}" for entry in entries if entry.kind == "decision"
        ],
        "questions": [entry.label() for entry in entries if entry.kind == "question"],
        "risks": [entry.label() for entry in entries if entry.kind == "risk"],
    }


def render_card(
    *,
    project: str,
    objective: str,
    as_of: str,
    sections: dict[str, list[str]],
    from_person: str = "",
    to_person: str = "",
) -> str:
    people = f"{from_person} → {to_person}" if from_person or to_person else "-"

    def block(title: str, lines: list[str]) -> str:
        if not lines:
            return f"## {title}（0）\n- 无\n"
        body = "\n".join(f"- {line}" for line in lines)
        return f"## {title}（{len(lines)}）\n{body}\n"

    parts = [
        f"# {project} · 交接卡",
        f"截至 {as_of}｜{people}\n",
        f"## 目标\n{objective}\n",
        block("已超期", sections["overdue"]),
        block("没人认领", sections["unassigned"]),
        block("进行中 / 待办", sections["open"]),
        block("已完成", sections["done"]),
        block("生效中的决定与约束", sections["decisions"]),
        block("风险", sections["risks"]),
        block("还没确认的问题", sections["questions"]),
    ]
    return "\n".join(parts)
