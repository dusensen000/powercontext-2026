"""Drive the published Dify Chatflow and record its workflow/node traces.

The judge rejected the earlier evidence because it only called the FastAPI
backend. This script instead talks to the *Dify web app* the way a browser does:
it obtains an app passport, starts a chat, and consumes the streaming SSE feed,
which carries Dify's own ``workflow_started`` / ``node_started`` /
``node_finished`` / ``workflow_finished`` events.

Two phases are expected to run in separate backend processes:

    python verify_dify_cloud.py night1   # reset + 赊账 + 撒谎
    # restart the tavern backend here
    python verify_dify_cloud.py night2   # new Dify conversation + 翻旧账 + 还账道歉

Required environment:
    DIFY_APP_CODE   code from https://udify.app/chat/<app-code>
Optional:
    DIFY_BASE       default https://udify.app/api
    DIFY_PROXY      e.g. http://127.0.0.1:7897 when the host needs a proxy
    TAVERN_API      default http://127.0.0.1:8770
    TAVERN_LOG_DIR  when set, the script records the backend log lines that
                    appeared during each turn (proves the http-request nodes
                    really reached seekdb/PowerContext)
    DIFY_EVIDENCE_DIR  default ../evidence/dify/cloud
    PLAYER_ID       default demo_alice
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = Path(os.environ.get("DIFY_EVIDENCE_DIR", ROOT / "evidence" / "dify" / "cloud"))
TAVERN_API = os.environ.get("TAVERN_API", "http://127.0.0.1:8770").rstrip("/")
LOG_DIR = Path(os.environ["TAVERN_LOG_DIR"]) if os.environ.get("TAVERN_LOG_DIR") else None
APP_CODE = os.environ.get("DIFY_APP_CODE", "").strip()
DIFY_BASE = os.environ.get("DIFY_BASE", "https://udify.app/api").rstrip("/")
DIFY_PROXY = os.environ.get("DIFY_PROXY", "").strip()
PLAYER_ID = os.environ.get("PLAYER_ID", "demo_alice")

NODE_ORDER = ["start_node", "recall_node", "llm_node", "remember_node", "answer_node"]
LEDGER_RE = re.compile(
    r"第(\d+)次照面.*?欠账 (\d+) 币.*?仇怨 (\d+) 格.*?本回合：([^\n·]+)"
)

TURNS = {
    "night1": [
        {
            "tag": "credit",
            "query": "老巴，来杯火焰威士忌，先记我账上，明天还你。",
            "visits": 1,
            "debt": 8,
            "grudge": 0,
            "label": "赊账",
            "intent": "credit",
            "delta_debt": 8,
            "delta_grudge": 0,
        },
        {
            "tag": "lie",
            "query": "我昨天说的是下周还，你可别记错了。",
            "visits": 2,
            "debt": 8,
            "grudge": 1,
            "label": "撒谎",
            "intent": "lie",
            "delta_debt": 0,
            "delta_grudge": 1,
        },
    ],
    "night2": [
        {
            "tag": "greeting",
            "query": "老巴，我又来了，今天有什么好酒？",
            "visits": 3,
            "debt": 8,
            "grudge": 1,
            "label": "闲聊",
            "intent": "chat",
            "delta_debt": 0,
            "delta_grudge": 0,
        },
        {
            "tag": "repay",
            "query": "对不起，上次是我不对。我这就还你 8 币。",
            "visits": 4,
            "debt": 0,
            "grudge": 0,
            "label": "还账并道歉",
            "intent": "repay_apology",
            "delta_debt": -8,
            "delta_grudge": -1,
        },
    ],
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Checker:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def check(self, ok: bool, message: str) -> bool:
        self.items.append({"ok": bool(ok), "message": message})
        print(("  [ok] " if ok else "  [FAIL] ") + message)
        return ok

    def require(self, ok: bool, message: str) -> None:
        if not self.check(ok, message):
            raise AssertionError(message)


def http_session() -> requests.Session:
    session = requests.Session()
    if DIFY_PROXY:
        session.proxies.update({"http": DIFY_PROXY, "https": DIFY_PROXY})
    session.headers.update({"User-Agent": "curl/8.9.1", "Accept": "*/*"})
    return session


def backend_health() -> Dict[str, Any]:
    response = requests.get(f"{TAVERN_API}/health", timeout=15)
    response.raise_for_status()
    return response.json()


def backend_state() -> Dict[str, Any]:
    response = requests.get(f"{TAVERN_API}/state", params={"player_id": PLAYER_ID}, timeout=30)
    response.raise_for_status()
    return response.json()


def backend_reset() -> Dict[str, Any]:
    response = requests.post(f"{TAVERN_API}/reset", json={"player_id": PLAYER_ID}, timeout=30)
    response.raise_for_status()
    return response.json()


def log_snapshot() -> Dict[str, List[str]]:
    if LOG_DIR is None:
        return {}
    snapshot: Dict[str, List[str]] = {}
    for name in ("app.log", "db_queries.log", "powercontext.log"):
        path = LOG_DIR / name
        if path.exists():
            snapshot[name] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return snapshot


def log_delta(before: Dict[str, List[str]], after: Dict[str, List[str]]) -> Dict[str, List[str]]:
    delta: Dict[str, List[str]] = {}
    for name, lines in after.items():
        previous = before.get(name, [])
        delta[name] = lines[len(previous):]
    return delta


def get_passport(http: requests.Session) -> str:
    response = http.get(
        f"{DIFY_BASE}/passport",
        params={"user_id": f"tavern-verify-{uuid.uuid4().hex[:12]}"},
        headers={"X-App-Code": APP_CODE},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def chat_turn(
    http: requests.Session,
    passport: str,
    query: str,
    conversation_id: Optional[str],
    user: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    body: Dict[str, Any] = {
        "inputs": {"player_id": PLAYER_ID},
        "query": query,
        "response_mode": "streaming",
        "user": user,
    }
    if conversation_id:
        body["conversation_id"] = conversation_id
    headers = {
        "X-App-Passport": passport,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    raw_lines: List[str] = []
    events: List[Dict[str, Any]] = []
    with http.post(
        f"{DIFY_BASE}/chat-messages",
        json=body,
        headers=headers,
        stream=True,
        timeout=(15, 240),
    ) as response:
        if response.status_code != 200:
            raise RuntimeError(f"Dify chat-messages -> {response.status_code}: {response.text[:600]}")
        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue
            raw_lines.append(line)
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
    return raw_lines, events


def summarize(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes_started: List[Dict[str, Any]] = []
    nodes_finished: List[Dict[str, Any]] = []
    run_ids: List[str] = []
    conversation_ids: List[str] = []
    message_ids: List[str] = []
    workflow: Dict[str, Any] = {}
    errors: List[Dict[str, Any]] = []
    answer = ""

    for event in events:
        name = event.get("event")
        data = event.get("data") or {}
        if event.get("workflow_run_id"):
            run_ids.append(str(event["workflow_run_id"]))
        if event.get("conversation_id"):
            conversation_ids.append(str(event["conversation_id"]))
        if event.get("message_id"):
            message_ids.append(str(event["message_id"]))
        if name == "node_started":
            nodes_started.append(
                {
                    "node_id": data.get("node_id"),
                    "node_type": data.get("node_type"),
                    "title": data.get("title"),
                    "index": data.get("index"),
                }
            )
        elif name == "node_finished":
            nodes_finished.append(
                {
                    "node_id": data.get("node_id"),
                    "node_type": data.get("node_type"),
                    "title": data.get("title"),
                    "index": data.get("index"),
                    "status": data.get("status"),
                    "elapsed_time": data.get("elapsed_time"),
                    "error": data.get("error"),
                }
            )
        elif name == "workflow_finished":
            workflow = {
                "run_id": data.get("id"),
                "workflow_id": data.get("workflow_id"),
                "status": data.get("status"),
                "total_steps": data.get("total_steps"),
                "total_tokens": data.get("total_tokens"),
                "elapsed_time": data.get("elapsed_time"),
                "error": data.get("error"),
            }
            answer = (data.get("outputs") or {}).get("answer") or ""
        elif name == "error":
            errors.append(data)

    unique = lambda values: list(dict.fromkeys(values))  # noqa: E731
    return {
        "run_ids": unique(run_ids),
        "conversation_ids": unique(conversation_ids),
        "message_ids": unique(message_ids),
        "nodes_started": nodes_started,
        "nodes_finished": nodes_finished,
        "workflow": workflow,
        "errors": errors,
        "answer": answer,
        "event_count": len(events),
    }


def parse_ledger(answer: str) -> Optional[Dict[str, Any]]:
    match = LEDGER_RE.search(answer)
    if not match:
        return None
    return {
        "visits": int(match.group(1)),
        "debt": int(match.group(2)),
        "grudge": int(match.group(3)),
        "label": match.group(4).strip(),
    }


def find_log(delta: Dict[str, List[str]], prefix: str) -> List[str]:
    return [line for line in delta.get("app.log", []) if line.split("\t")[1:2] == [prefix]]


def trace_assertions(
    checker: Checker,
    summary: Dict[str, Any],
    state: Dict[str, Any],
    turn: Dict[str, Any],
    delta: Dict[str, List[str]],
    night: str,
) -> None:
    tag = turn["tag"]
    workflow = summary["workflow"]
    finished = summary["nodes_finished"]
    node_ids = [node["node_id"] for node in finished]

    checker.require(not summary["errors"], f"{tag}: Dify SSE has no error event")
    checker.require(
        workflow.get("status") == "succeeded",
        f"{tag}: workflow_finished status=succeeded (got {workflow.get('status')})",
    )
    checker.require(
        workflow.get("total_steps") == 5,
        f"{tag}: workflow ran 5 steps (got {workflow.get('total_steps')})",
    )
    checker.require(
        node_ids == NODE_ORDER,
        f"{tag}: node_finished covers Start→recall→LLM→remember→Answer in order",
    )
    checker.require(
        len(summary["nodes_started"]) == 5,
        f"{tag}: 5 node_started events (got {len(summary['nodes_started'])})",
    )
    checker.require(
        all(node.get("status") == "succeeded" for node in finished),
        f"{tag}: every node_finished status=succeeded",
    )
    checker.require(
        len(summary["run_ids"]) == 1 and summary["run_ids"][0] == workflow.get("run_id"),
        f"{tag}: one workflow_run_id shared by all node events",
    )
    checker.require(
        len(summary["conversation_ids"]) == 1,
        f"{tag}: one conversation_id for the streaming run",
    )
    recall = next((node for node in finished if node["node_id"] == "recall_node"), {})
    remember = next((node for node in finished if node["node_id"] == "remember_node"), {})
    checker.require(
        (recall.get("elapsed_time") or 0) > 0.01,
        f"{tag}: recall_node really made an HTTP call ({recall.get('elapsed_time')}s)",
    )
    checker.require(
        (remember.get("elapsed_time") or 0) > 0.01,
        f"{tag}: remember_node really made an HTTP call ({remember.get('elapsed_time')}s)",
    )

    answer = summary["answer"]
    ledger = parse_ledger(answer)
    checker.require(ledger is not None, f"{tag}: Answer contains the backend ledger line")
    if ledger:
        checker.require(
            (ledger["visits"], ledger["debt"], ledger["grudge"])
            == (turn["visits"], turn["debt"], turn["grudge"]),
            f"{tag}: ledger line = 第{turn['visits']}次照面/欠账 {turn['debt']}/仇怨 {turn['grudge']}"
            f" (got 第{ledger['visits']}次/欠账 {ledger['debt']}/仇怨 {ledger['grudge']})",
        )
        checker.require(
            turn["label"] in ledger["label"],
            f"{tag}: ledger label contains {turn['label']} (got {ledger['label']!r})",
        )
    checker.require(
        "记忆已写入 PowerContext" in answer,
        f"{tag}: Answer reports the PowerContext write",
    )

    player = state["player"]
    checker.require(
        (int(player["visits"]), int(player["debt"]), int(player["grudge"]))
        == (turn["visits"], turn["debt"], turn["grudge"]),
        f"{tag}: backend /state visits/debt/grudge = "
        f"{turn['visits']}/{turn['debt']}/{turn['grudge']}",
    )

    recalls = find_log(delta, "recall")
    remembers = find_log(delta, "remember")
    checker.require(
        any(f"player={PLAYER_ID}" in line for line in recalls),
        f"{tag}: backend app.log shows the recall HTTP node arrival",
    )
    checker.require(
        any(f"player={PLAYER_ID}" in line for line in remembers),
        f"{tag}: backend app.log shows the remember HTTP node arrival",
    )
    expected_remember = (
        f"intent={turn['intent']} delta_debt={turn['delta_debt']} "
        f"delta_grudge={turn['delta_grudge']}"
    )
    checker.require(
        any(expected_remember in line for line in remembers),
        f"{tag}: backend settlement {expected_remember}",
    )
    if night == "night2" and tag == "greeting":
        counts = []
        for line in recalls:
            match = re.search(r"memories=(\d+)", line)
            if match:
                counts.append(int(match.group(1)))
        checker.require(
            bool(counts) and max(counts) >= 2,
            f"{tag}: cross-session recall returned >=2 old memories (got {counts})",
        )
        offline = answer.split("—— 老巴的账本")[0]
        checker.require(
            bool(re.search(r"8|八", offline)),
            f"{tag}: 老巴's own line mentions the 8-coin debt",
        )
        old_case = ["撒谎", "改口", "昨天", "上次", "上回", "旧账", "假眼", "记错"]
        checker.require(
            any(word in offline for word in old_case),
            f"{tag}: 老巴's own line brings up the old lie",
        )


def save_turn(night: str, index: int, record: Dict[str, Any], raw_lines: List[str], events: List[Dict[str, Any]]) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stem = str(EVIDENCE / f"{night}-turn{index}")
    Path(stem + ".sse.txt").write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    Path(stem + ".trace.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(stem + ".events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_night(night: str) -> int:
    if not APP_CODE:
        raise SystemExit("DIFY_APP_CODE is required (the code after https://udify.app/chat/)")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    checker = Checker()
    http = http_session()
    print(f"[{night}] Dify app {APP_CODE} @ {DIFY_BASE}")
    print(f"[{night}] player={PLAYER_ID} backend={TAVERN_API}")

    health = backend_health()
    (EVIDENCE / f"health-{night}.json").write_text(
        json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checker.require(health.get("ok") is True, f"{night}: backend /health ok")
    checker.require(
        health.get("db_backend") == "seekdb",
        f"{night}: backend ledger is seekdb (got {health.get('db_backend')})",
    )
    checker.require(
        health.get("powercontext_ok") is True,
        f"{night}: PowerContext reachable",
    )

    if night == "night1":
        reset = backend_reset()
        print(f"[{night}] reset: {reset['note']}")
    else:
        previous_path = EVIDENCE / "night1.json"
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
            previous_pid = (previous.get("health") or {}).get("pid")
            checker.require(
                previous_pid is not None and previous_pid != health.get("pid"),
                f"{night}: backend process restarted (pid {previous_pid} -> {health.get('pid')})",
            )
        state_before = backend_state()
        player = state_before["player"]
        checker.require(
            (int(player["visits"]), int(player["debt"]), int(player["grudge"])) == (2, 8, 1),
            f"{night}: new process still recalls visits=2/debt=8/grudge=1 from seekdb",
        )
        checker.require(
            len(state_before.get("memories") or []) >= 2,
            f"{night}: new process still recalls >=2 PowerContext memories "
            f"(got {len(state_before.get('memories') or [])})",
        )
        (EVIDENCE / "state-before-night2.json").write_text(
            json.dumps(state_before, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    passport = get_passport(http)
    user = f"tavern-{PLAYER_ID}-{night}-{uuid.uuid4().hex[:6]}"
    conversation_id: Optional[str] = None
    turns_out: List[Dict[str, Any]] = []

    for index, turn in enumerate(TURNS[night], start=1):
        print(f"[{night}] turn {index}: {turn['query']}")
        before = log_snapshot()
        started = now()
        raw_lines, events = chat_turn(http, passport, turn["query"], conversation_id, user)
        finished = now()
        delta = log_delta(before, log_snapshot())
        summary = summarize(events)
        if not conversation_id and summary["conversation_ids"]:
            conversation_id = summary["conversation_ids"][0]
        state = backend_state()
        checks_before = len(checker.items)
        trace_assertions(checker, summary, state, turn, delta, night)
        turn_checks = checker.items[checks_before:]

        record = {
            "night": night,
            "turn": index,
            "tag": turn["tag"],
            "query": turn["query"],
            "started_at": started,
            "finished_at": finished,
            "user": user,
            "conversation_id": conversation_id,
            "workflow_run_id": (summary["workflow"] or {}).get("run_id"),
            "workflow": summary["workflow"],
            "nodes_started": summary["nodes_started"],
            "nodes_finished": summary["nodes_finished"],
            "answer": summary["answer"],
            "ledger": parse_ledger(summary["answer"]),
            "backend_log_delta": delta,
            "state_after": state,
            "assertions": turn_checks,
        }
        save_turn(night, index, record, raw_lines, events)
        turns_out.append(
            {
                "turn": index,
                "tag": turn["tag"],
                "query": turn["query"],
                "started_at": started,
                "finished_at": finished,
                "conversation_id": conversation_id,
                "workflow_run_id": record["workflow_run_id"],
                "workflow_status": record["workflow"].get("status"),
                "total_steps": record["workflow"].get("total_steps"),
                "nodes": summary["nodes_finished"],
                "ledger": record["ledger"],
                "answer": summary["answer"],
                "backend_log_delta": delta,
                "assertions": record["assertions"],
            }
        )
        print(f"  answer: {summary['answer'].strip()[:220]}")
        for node in summary["nodes_finished"]:
            print(
                f"  node {node['index']}. {node['node_id']} ({node['node_type']}) "
                f"{node['status']} {node['elapsed_time']}s"
            )

    state_after = backend_state()
    if night == "night1":
        checker.require(
            len(state_after.get("memories") or []) >= 2,
            f"{night}: PowerContext holds >=2 turn memories "
            f"(got {len(state_after.get('memories') or [])})",
        )
        checker.require(
            len(state_after.get("recent_turns") or []) == 2,
            f"{night}: seekdb turns table has 2 rows for this epoch",
        )
    else:
        checker.require(
            len(state_after.get("recent_turns") or []) == 4,
            f"{night}: seekdb turns table has 4 rows for this epoch",
        )
        checker.require(
            len(state_after.get("memories") or []) >= 4,
            f"{night}: PowerContext holds >=4 memories after night 2",
        )

    ok = all(item["ok"] for item in checker.items)
    result = {
        "night": night,
        "ok": ok,
        "app_code": APP_CODE,
        "dify_base": DIFY_BASE,
        "tavern_api": TAVERN_API,
        "player_id": PLAYER_ID,
        "health": health,
        "turns": turns_out,
        "state_after": state_after,
        "assertions": checker.items,
    }
    (EVIDENCE / f"{night}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{night}] {'PASS' if ok else 'FAIL'} -> {EVIDENCE / (night + '.json')}")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("night", choices=["night1", "night2"])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(run_night(args.night))
    except requests.RequestException as exc:
        print(f"[error] HTTP failure: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
