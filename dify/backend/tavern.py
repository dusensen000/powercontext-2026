"""Deterministic tavern rules.

The LLM writes 老巴's words; this module decides what actually happens to the
ledger (debt / grudge) so the demo is reproducible across models.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

CREDIT_KW = ["赊", "记我账", "记在账上", "记账", "先欠", "欠着", "改天还", "下次还", "回头还", "明天还你"]
REPAY_KW = ["还钱", "还账", "还债", "结账", "结清", "这就还", "现在还", "马上还", "还给你", "把账结了"]
APOLOGY_KW = ["对不起", "抱歉", "我错了", "道歉", "原谅我"]
LIE_KW = ["骗", "撒谎", "胡说", "耍你", "逗你", "假的", "编的", "记错", "其实我"]
THEFT_KW = ["偷", "顺走", "拿走", "揣走", "不告而取"]
PURCHASE_KW = ["来一杯", "来一壶", "来杯", "点一杯", "买", "喝"]
GOSSIP_KW = ["听说", "传闻", "故事", "打听", "告诉我", "有没有", "讲讲"]

LABELS = {
    "credit": "赊账",
    "repay": "还账",
    "repay_apology": "还账并道歉",
    "lie": "撒谎",
    "theft": "偷窃",
    "apology": "道歉",
    "purchase": "买酒",
    "gossip": "打听",
    "chat": "闲聊",
}


def _has(text: str, words: List[str]) -> Optional[str]:
    for word in words:
        if word in text:
            return word
    return None


def _amount(message: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*(?:币|块|枚|个硬币)", message)
    return int(match.group(1)) if match else None


def _item(message: str, lore_hits: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    drinks = [card for card in lore_hits if card.get("category") == "drink"]
    for card in drinks:
        if card["title"] in message:
            return card
    return drinks[0] if drinks else None


def analyze(
    message: str,
    player: Dict[str, Any],
    lore_hits: List[Dict[str, Any]],
) -> Dict[str, Any]:
    text = message.strip()
    debt = int(player.get("debt") or 0)
    grudge = int(player.get("grudge") or 0)
    item = _item(text, lore_hits)
    price = int(item["price"]) if item else 5

    credit_kw = _has(text, CREDIT_KW)
    repay_kw = _has(text, REPAY_KW)
    apology_kw = _has(text, APOLOGY_KW)
    lie_kw = _has(text, LIE_KW)
    theft_kw = _has(text, THEFT_KW)
    purchase_kw = _has(text, PURCHASE_KW)
    gossip_kw = _has(text, GOSSIP_KW)

    delta_debt = 0
    delta_grudge = 0
    intent = "chat"
    note = ""
    matched = []

    # Repay wins over everything else: handing over money is unambiguous.
    if repay_kw:
        matched.append(repay_kw)
        wanted = _amount(text)
        paid = debt if wanted is None else min(debt, wanted)
        delta_debt -= paid
        intent = "repay"
        note = f"收下 {paid} 币" if paid else "账上本来就没钱可还"
        if apology_kw:
            matched.append(apology_kw)
            delta_grudge -= 1
            intent = "repay_apology"
            note += "，并接受了道歉"
    elif theft_kw:
        matched.append(theft_kw)
        intent = "theft"
        fine = price * 2
        delta_debt += fine
        delta_grudge += 2
        note = f"顺走{item['title'] if item else '酒杯'}，按规矩赔双倍 {fine} 币，记仇两格"
    elif lie_kw:
        matched.append(lie_kw)
        intent = "lie"
        delta_grudge += 1
        note = "被假眼识破，记仇一格"
    elif credit_kw:
        matched.append(credit_kw)
        intent = "credit"
        interest = 1 if debt > 0 else 0
        delta_debt += price + interest
        note = f"赊下{item['title'] if item else '一杯酒'}（{price} 币）"
        if interest:
            note += "，旧账未清另加 1 币利息"
    elif apology_kw:
        matched.append(apology_kw)
        intent = "apology"
        delta_grudge -= 1
        note = "接受道歉，仇怨减一格"
    elif purchase_kw:
        matched.append(purchase_kw)
        intent = "purchase"
        note = f"现金买下{item['title'] if item else '一杯酒'}，两清"
    elif gossip_kw:
        matched.append(gossip_kw)
        intent = "gossip"
        note = "凑近讲了一条店里的传闻"

    new_debt = max(0, debt + delta_debt)
    new_grudge = max(0, min(9, grudge + delta_grudge))
    # Report what actually changed after clamping.
    delta_debt = new_debt - debt
    delta_grudge = new_grudge - grudge

    return {
        "intent": intent,
        "label": LABELS[intent],
        "note": note,
        "matched": matched,
        "item": {"title": item["title"], "price": price} if item else None,
        "delta_debt": delta_debt,
        "delta_grudge": delta_grudge,
        "debt_after": new_debt,
        "grudge_after": new_grudge,
    }


def memory_text(
    *,
    player_id: str,
    visits: int,
    message: str,
    reply: str,
    verdict: Dict[str, Any],
    debt: int,
    grudge: int,
) -> str:
    return (
        f"记忆酒馆·第{visits}次照面｜玩家 {player_id} 说：“{' '.join(message.split())[:120]}”"
        f"｜老巴回：“{' '.join(reply.split())[:160]}”"
        f"｜判定：{verdict['label']}（{verdict['note']}）"
        f"｜回合变化：欠账{verdict['delta_debt']:+d}，仇怨{verdict['delta_grudge']:+d}"
        f"｜当前欠账 {debt} 币，仇怨 {grudge} 格。"
    )
