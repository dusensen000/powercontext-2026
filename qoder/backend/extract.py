from __future__ import annotations

import re

from .llm import chat_json
from .schema import ALL_STATUSES, KINDS, WorkItem

SYSTEM_PROMPT = """你是项目助理，从会议纪要或聊天记录里抽取结构化工作条目。

只输出 JSON，不要任何解释文字。格式：
{"items": [{"kind": "", "title": "", "detail": "", "owner": "", "due": "", "status": "", "keywords": "", "confidence": 0.0}]}

字段规则：
- kind 只能是 decision / action / risk / question 之一。
  - decision：已经拍板的结论、口径或时间点。
  - action：某人要做的具体事情，尽量填 owner 和 due。
  - risk：可能出问题的点。
  - question：还没确认、需要别人回答的问题。
- title：不超过 20 个字，能独立看懂。
- detail：保留原文关键信息（数字、日期、人名），不要编造，不要总结成空话。
- owner：负责人姓名，没有就留空。
- due：截止日期，格式 YYYY-MM-DD，没有就留空。原文只写月日时，用「记录日期」的年份补全；
  若补出的月份早于记录月份，说明是次年，年份加一。不要凭印象补年份。
- status 只能是 open / in_progress / done / blocked 之一。
  - 原文明确说已经做完、已交付、已上线，才填 done。
  - 原文说被卡住、等排期、没人接手，填 blocked。
  - 原文说已经开工、方案已完成但目标未达到，填 in_progress。
  - 只是布置了任务还没开始，填 open。
- keywords：2 到 3 个短关键词，用英文逗号分隔，每个 2 到 6 个字，用于全文检索。
- confidence：0 到 1 的小数，表示这条抽取的把握。
- 抽不到任何条目就返回 {"items": []}。"""


def meeting_date(text: str) -> str:
    """从纪要正文里取记录日期，取不到返回空串。"""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else ""


def extract_items(text: str, *, project: str, source: str) -> list[WorkItem]:
    date = meeting_date(text)
    header = f"项目：{project}\n来源：{source}\n记录日期：{date or '未知'}"
    payload = chat_json(SYSTEM_PROMPT, f"{header}\n\n{text}")
    items: list[WorkItem] = []
    for raw in payload.get("items", []):
        kind = str(raw.get("kind", "")).strip()
        title = str(raw.get("title", "")).strip()
        if kind not in KINDS or not title:
            continue
        try:
            confidence = float(raw.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        status = str(raw.get("status") or "open").strip()
        if status not in ALL_STATUSES:
            status = "open"
        items.append(
            WorkItem(
                project=project,
                kind=kind,
                title=title,
                detail=str(raw.get("detail", "")).strip(),
                owner=str(raw.get("owner") or "").strip(),
                due=str(raw.get("due") or "").strip(),
                status=status,
                source=source,
                keywords=str(raw.get("keywords") or "").strip(),
                confidence=confidence,
            )
        )
    return items
