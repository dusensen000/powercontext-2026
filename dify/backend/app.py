"""Memory Tavern HTTP backend used by the Dify Chatflow.

Dify calls ``/recall`` before the LLM node and ``/remember`` after it. seekdb
holds the lore cards, the player ledger and the turn log; PowerContext holds the
episodic memories that survive across Dify conversations.
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError

import config
import tavern
from db import TavernDB
from memory import MemoryError_, PowerContextClient

_db: Optional[TavernDB] = None
_memory: Optional[PowerContextClient] = None


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _log(action: str, detail: str) -> None:
    config.ensure_dirs()
    with (config.LOG_DIR / "app.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{_now()}\t{action}\t{detail}\n")


def db() -> TavernDB:
    if _db is None:
        raise RuntimeError("database not initialised")
    return _db


def memory() -> PowerContextClient:
    if _memory is None:
        raise RuntimeError("memory client not initialised")
    return _memory


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _db, _memory
    config.ensure_dirs()
    _db = TavernDB()
    seeded = _db.seed_lore()
    _memory = PowerContextClient()
    _log(
        "start",
        f"backend={_db.backend} db={_db.db_name} seeded={seeded} "
        f"powercontext={_memory.url} alive={_memory.health()}",
    )
    try:
        yield
    finally:
        _log("stop", "server shutting down")
        _db.close()
        _db = None


app = FastAPI(title="Memory Tavern", version="1.0.0", lifespan=lifespan)


class RecallIn(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)


class RememberIn(RecallIn):
    reply: str = Field(min_length=1, max_length=4000)


class ResetIn(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)


def _player_id(value: str) -> str:
    clean = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{1,64}", clean):
        raise HTTPException(400, "player_id 只能包含字母、数字、下划线、连字符或汉字")
    return clean


def _ensure_scope(player: Dict[str, Any]) -> str:
    return memory().ensure_scope(
        player["player_id"],
        int(player["epoch"]),
        player.get("pc_scope_id"),
        lambda scope_id: db().set_scope(player["player_id"], scope_id),
        nonce=uuid.uuid4().hex[:6] if not player.get("pc_scope_id") else "",
    )


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "db_backend": db().backend,
        "db_name": db().db_name,
        "lore": db().count_lore(),
        "powercontext": memory().url,
        "powercontext_ok": memory().health(),
    }


async def _payload(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = {key: str(value) for key, value in form.items()}
    if not isinstance(data, dict):
        raise HTTPException(400, "请求体必须是 JSON 对象或表单")
    return data


@app.post("/recall")
async def recall(request: Request) -> Dict[str, Any]:
    try:
        body = RecallIn(**await _payload(request))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc
    player_id = _player_id(body.player_id)
    message = body.message.strip()
    player = db().get_player(player_id)
    lore = db().match_lore(message, limit=3)
    special = db().daily_special(player_id + message)
    rules = db().lore_cards("rule")[:2]
    ledger_tail = db().recent_turns(player_id, int(player["epoch"]), limit=3)

    memories: List[Dict[str, Any]] = []
    memory_warning = None
    scope_id = None
    try:
        scope_id = _ensure_scope(player)
        query = f"{message} 欠账 {player.get('debt', 0)} 仇怨 {player.get('grudge', 0)} 上次 老巴"
        memories = memory().search(scope_id, query, limit=5)
    except MemoryError_ as exc:
        memory_warning = str(exc)
        _log("recall", f"player={player_id} memory_error={memory_warning}")

    if int(player.get("grudge") or 0) > 0:
        hint = "先翻旧账，再谈别的；语气不爽，但别直接赶人。"
    elif int(player.get("debt") or 0) > 0:
        hint = "先提欠账和上次的借口，再招呼他坐下。"
    elif int(player.get("visits") or 0) == 0:
        hint = "第一次见，按生客招呼，但记住他的名字。"
    else:
        hint = "熟人回店，先提一件上次的旧事，再问今天想要什么。"

    payload = {
        "player": {
            "player_id": player_id,
            "visits": int(player.get("visits") or 0),
            "debt": int(player.get("debt") or 0),
            "grudge": int(player.get("grudge") or 0),
            "last_seen": player.get("last_seen"),
            "epoch": int(player.get("epoch") or 0),
        },
        "lore": [
            {
                "title": card["title"],
                "category": card["category"],
                "price": card["price"],
                "content": card["content"],
            }
            for card in lore
        ],
        "daily_special": (
            {"title": special["title"], "price": special["price"], "content": special["content"]}
            if special
            else None
        ),
        "rules": [{"title": card["title"], "content": card["content"]} for card in rules],
        "memories": memories,
        "ledger_tail": ledger_tail,
        "greeting_hint": hint,
        "storage": {
            "ledger_and_lore": db().backend,
            "episodic_memory": "powercontext" if not memory_warning else "powercontext(unavailable)",
            "scope_id": scope_id,
        },
    }
    if memory_warning:
        payload["memory_warning"] = memory_warning
    _log(
        "recall",
        f"player={player_id} visits={payload['player']['visits']} debt={payload['player']['debt']} "
        f"grudge={payload['player']['grudge']} lore={len(lore)} memories={len(memories)}",
    )
    return payload


@app.post("/remember")
async def remember(request: Request, fmt: str = Query("text", pattern="^(text|json)$")):
    try:
        body = RememberIn(**await _payload(request))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc
    player_id = _player_id(body.player_id)
    message = body.message.strip()
    reply = body.reply.strip()
    player = db().get_player(player_id)
    lore = db().match_lore(message, limit=3)
    verdict = tavern.analyze(message, player, lore)

    visits = int(player.get("visits") or 0) + 1
    updated = db().update_player(
        player_id,
        visits=visits,
        debt=verdict["debt_after"],
        grudge=verdict["grudge_after"],
        last_seen=_now(),
        memo=verdict["note"],
    )
    db().add_turn(
        player_id=player_id,
        epoch=int(updated["epoch"]),
        message=message,
        reply=reply,
        intent=verdict["intent"],
        delta_debt=verdict["delta_debt"],
        delta_grudge=verdict["delta_grudge"],
    )

    memory_warning = None
    scope_id = None
    text = tavern.memory_text(
        player_id=player_id,
        visits=visits,
        message=message,
        reply=reply,
        verdict=verdict,
        debt=verdict["debt_after"],
        grudge=verdict["grudge_after"],
    )
    try:
        scope_id = _ensure_scope(updated)
        memory().remember(scope_id, text, reason=f"tavern turn {visits} / {verdict['label']}")
    except MemoryError_ as exc:
        memory_warning = str(exc)
        _log("remember", f"player={player_id} memory_error={memory_warning}")

    state_line = (
        f"—— 老巴的账本：第{visits}次照面 · 欠账 {verdict['debt_after']} 币 · "
        f"仇怨 {verdict['grudge_after']} 格 · 本回合：{verdict['label']}" + (f"（{verdict['note']}）" if verdict["note"] else "")
    )
    if memory_warning:
        state_line += " · 记忆服务暂不可用"
    else:
        state_line += f" · 记忆已写入 PowerContext（{str(scope_id)[:12]}…）"

    _log(
        "remember",
        f"player={player_id} intent={verdict['intent']} delta_debt={verdict['delta_debt']} "
        f"delta_grudge={verdict['delta_grudge']} debt={verdict['debt_after']} "
        f"grudge={verdict['grudge_after']} memory={'ok' if not memory_warning else 'error'}",
    )
    if fmt == "json":
        return {
            "player": updated,
            "verdict": verdict,
            "state_line": state_line,
            "scope_id": scope_id,
            "memory_warning": memory_warning,
        }
    return PlainTextResponse(state_line)


@app.get("/state")
def state(player_id: str = Query(..., min_length=1, max_length=64)) -> Dict[str, Any]:
    player_id = _player_id(player_id)
    player = db().get_player(player_id)
    turns = db().recent_turns(player_id, int(player["epoch"]), limit=10)
    memories: List[Dict[str, Any]] = []
    try:
        scope_id = _ensure_scope(player)
        memories = memory().search(scope_id, "欠账 仇怨 老巴 上次", limit=10)
    except MemoryError_ as exc:
        memories = [{"error": str(exc)}]
    return {"player": player, "recent_turns": turns, "memories": memories}


@app.post("/reset")
def reset(body: ResetIn) -> Dict[str, Any]:
    player_id = _player_id(body.player_id)
    player = db().reset_player(player_id)
    _log("reset", f"player={player_id} new_epoch={player['epoch']}")
    return {
        "ok": True,
        "player": player,
        "note": f"账本翻篇：{db().backend} 中该玩家的状态与回合已清零，PowerContext 改用新一代 scope，旧记忆不再参与。",
    }


@app.get("/lore")
def lore(q: str = Query("", max_length=200)) -> Dict[str, Any]:
    cards = db().match_lore(q, limit=5) if q else db().lore_cards()[:5]
    return {"query": q, "count": db().count_lore(), "cards": cards}


@app.get("/")
def index() -> Dict[str, Any]:
    return {
        "name": "记忆酒馆 backend",
        "endpoints": ["/health", "/recall", "/remember", "/state", "/reset", "/lore"],
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=False)
