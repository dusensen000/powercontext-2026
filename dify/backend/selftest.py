"""Two-session smoke test for the Memory Tavern backend.

The Dify Chatflow itself generates 老巴's lines with an LLM. To prove the
*backend* half without an API key, this script replays the same HTTP calls with
a deterministic mock bartender, so the seekdb ledger and PowerContext memories
can be inspected end to end.

Usage (backend already running):
    python selftest.py session1   # reset, then two turns: 赊账 + 撒谎
    # restart the backend here (optional, proves state lives outside the process)
    python selftest.py session2   # greeting must recall the debt and the lie, then repay
    python selftest.py all        # both sessions in one process
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict

import config

PLAYER = "demo_alice"


def _call(method: str, path: str, payload: Dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    request = urllib.request.Request(
        f"{config.API}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise SystemExit(f"backend unreachable at {config.API}: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def _recall(message: str) -> Dict[str, Any]:
    return _call("POST", "/recall", {"player_id": PLAYER, "message": message})


def _remember(message: str, reply: str) -> str:
    return _call("POST", "/remember", {"player_id": PLAYER, "message": message, "reply": reply})


def _state() -> Dict[str, Any]:
    return _call("GET", f"/state?player_id={PLAYER}")


def mock_reply(tag: str, recall: Dict[str, Any]) -> str:
    player = recall["player"]
    debt = player["debt"]
    grudge = player["grudge"]
    if tag == "credit":
        return "火焰威士忌？行。杯垫上签个名——八币，明天这个时辰，我等你。"
    if tag == "lie":
        return (
            f"你昨天说的是‘明天还’，今天又改口下周？我左眼不眨，不代表它瞎。"
            f"这 {debt} 币我记下了，仇也记一格。"
        )
    if tag == "greeting":
        memory_hint = ""
        if recall.get("memories"):
            memory_hint = "你上回的原话我还留着呢。"
        return (
            f"又来了？先别急着点酒。你欠我 {debt} 币，{memory_hint}"
            f"我左眼把你上次改口的样子记得清清楚楚。"
        )
    if tag == "repay":
        return f"……行，{debt} 币放下。杯子还给你留着，别再让我用假眼盯你。"
    return f"老巴看了你一眼：欠账 {debt} 币，仇怨 {grudge} 格。"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  [ok] {message}")


def _dump_session(name: str, steps: list[Dict[str, Any]], state: Dict[str, Any]) -> None:
    config.ensure_dirs()
    path = config.EVIDENCE_DIR / f"{name}.json"
    path.write_text(
        json.dumps(
            {"player_id": PLAYER, "api": config.API, "steps": steps, "state_after": state},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  evidence -> {path}")


def session1() -> None:
    print("[session 1] reset + 赊账 + 撒谎")
    print(_call("POST", "/reset", {"player_id": PLAYER})["note"])
    steps = []

    message = "老巴，来杯火焰威士忌，先记我账上，明天还你。"
    recall = _recall(message)
    reply = mock_reply("credit", recall)
    state_line = _remember(message, reply)
    steps.append({"message": message, "recall": recall, "reply": reply, "state_line": state_line})
    print(f"  player: {message}\n  bartender: {reply}\n  {state_line}")

    message = "我昨天说的是下周还，你可别记错了。"
    recall = _recall(message)
    reply = mock_reply("lie", recall)
    state_line = _remember(message, reply)
    steps.append({"message": message, "recall": recall, "reply": reply, "state_line": state_line})
    print(f"  player: {message}\n  bartender: {reply}\n  {state_line}")

    state = _state()
    player = state["player"]
    _check(player["debt"] == 8, f"seekdb ledger: debt == 8 (got {player['debt']})")
    _check(player["grudge"] == 1, f"seekdb ledger: grudge == 1 (got {player['grudge']})")
    _check(player["visits"] == 2, f"seekdb ledger: visits == 2 (got {player['visits']})")
    _check(
        len(state.get("memories") or []) >= 2,
        f"PowerContext holds at least 2 turn memories (got {len(state.get('memories') or [])})",
    )
    _dump_session("session1", steps, state)


def session2() -> None:
    print("[session 2] new Dify conversation, same player_id")
    steps = []

    message = "老巴，我又来了，今天有什么好酒？"
    recall = _recall(message)
    player = recall["player"]
    memories = recall.get("memories") or []
    _check(player["debt"] == 8, f"cross-session recall: debt == 8 (got {player['debt']})")
    _check(player["grudge"] == 1, f"cross-session recall: grudge == 1 (got {player['grudge']})")
    _check(len(memories) >= 2, f"cross-session recall: memories >= 2 (got {len(memories)})")
    reply = mock_reply("greeting", recall)
    state_line = _remember(message, reply)
    steps.append({"message": message, "recall": recall, "reply": reply, "state_line": state_line})
    print(f"  player: {message}\n  bartender: {reply}\n  {state_line}")
    print(f"  recalled memories: {len(memories)}")
    for hit in memories[:3]:
        print(f"    - {hit.get('text', '')[:96]}")

    message = "对不起，上次是我不对。我这就还你 8 币。"
    recall = _recall(message)
    reply = mock_reply("repay", recall)
    state_line = _remember(message, reply)
    steps.append({"message": message, "recall": recall, "reply": reply, "state_line": state_line})
    print(f"  player: {message}\n  bartender: {reply}\n  {state_line}")

    state = _state()
    player = state["player"]
    _check(player["debt"] == 0, f"after repay: debt == 0 (got {player['debt']})")
    _check(player["grudge"] == 0, f"after apology: grudge == 0 (got {player['grudge']})")
    _dump_session("session2", steps, state)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    started = time.time()
    print(f"API: {config.API}")
    if mode in ("session1", "all"):
        session1()
    if mode in ("session2", "all"):
        session2()
    print(f"done in {time.time() - started:.2f}s")


if __name__ == "__main__":
    main()
