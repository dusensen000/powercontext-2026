"""seekdb storage for tavern lore, player ledgers and turn logs.

The default backend is OceanBase **seekdb** through ``pylibseekdb`` + PyMySQL.
A ``sqlite`` backend exists only for quick smoke tests on hosts where the
seekdb wheel is unavailable; the submitted evidence was produced with seekdb.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List

import config


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _log(sql: str, params: Iterable[Any], rows: int, backend: str, db_name: str) -> None:
    config.ensure_dirs()
    line = (
        f"{_now()}\tbackend={backend}\tdb={db_name}\trows={rows}\t"
        f"params={list(params)!r}\tsql={' '.join(sql.split())}\n"
    )
    with (config.LOG_DIR / "db_queries.log").open("a", encoding="utf-8") as fh:
        fh.write(line)


class TavernDB:
    def __init__(
        self,
        backend: str | None = None,
        path: str | None = None,
        db_name: str | None = None,
    ) -> None:
        self.backend = backend or config.DB_BACKEND
        self.path = path or config.DB_PATH
        self.db_name = db_name or config.DB_NAME
        self._ph = "%s" if self.backend == "seekdb" else "?"
        self._conn = None
        self._handle = None
        self._lock = threading.Lock()
        self._open()

    # -- connection ------------------------------------------------------------
    def _open(self) -> None:
        if self.backend == "sqlite":
            import sqlite3

            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        elif self.backend == "seekdb":
            try:
                import pylibseekdb as seekdb  # type: ignore
                import pymysql
            except ImportError as exc:
                raise RuntimeError(
                    "seekdb backend needs pylibseekdb (Linux wheel) and pymysql; "
                    "run inside the Dify host/Linux and install requirements.txt, "
                    "or set TAVERN_DB_BACKEND=sqlite only for a local smoke test"
                ) from exc

            self._pymysql = pymysql
            self._seekdb = seekdb
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._handle = seekdb.open(self.path)
            opts = {
                key: value
                for key, value in dict(self._handle.connection_options()).items()
                if key not in ("database", "db") and value is not None
            }
            bootstrap = pymysql.connect(**opts, autocommit=True)
            with bootstrap.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.db_name}` "
                    "DEFAULT CHARACTER SET utf8mb4"
                )
            bootstrap.close()
            self._conn = pymysql.connect(
                **opts,
                database=self.db_name,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
        else:
            raise ValueError(f"unknown DB backend: {self.backend}")
        self._create_schema()

    def _create_schema(self) -> None:
        if self.backend == "sqlite":
            ddl = [
                (
                    "CREATE TABLE IF NOT EXISTS lore ("
                    "id INTEGER PRIMARY KEY, category TEXT, title TEXT, content TEXT,"
                    "keywords TEXT, price INTEGER DEFAULT 0)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS players ("
                    "player_id TEXT PRIMARY KEY, epoch INTEGER DEFAULT 0,"
                    "pc_scope_id TEXT, visits INTEGER DEFAULT 0, debt INTEGER DEFAULT 0,"
                    "grudge INTEGER DEFAULT 0, last_seen TEXT, memo TEXT)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS turns ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, player_id TEXT, epoch INTEGER,"
                    "ts TEXT, message TEXT, reply TEXT, intent TEXT,"
                    "delta_debt INTEGER, delta_grudge INTEGER)"
                ),
            ]
        else:
            ddl = [
                (
                    "CREATE TABLE IF NOT EXISTS lore ("
                    "id INT PRIMARY KEY, category VARCHAR(32), title VARCHAR(128),"
                    "content TEXT, keywords VARCHAR(255), price INT DEFAULT 0)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS players ("
                    "player_id VARCHAR(64) PRIMARY KEY, epoch INT DEFAULT 0,"
                    "pc_scope_id VARCHAR(80), visits INT DEFAULT 0, debt INT DEFAULT 0,"
                    "grudge INT DEFAULT 0, last_seen VARCHAR(32), memo TEXT)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS turns ("
                    "id BIGINT PRIMARY KEY AUTO_INCREMENT, player_id VARCHAR(64),"
                    "epoch INT, ts VARCHAR(32), message TEXT, reply TEXT,"
                    "intent VARCHAR(32), delta_debt INT, delta_grudge INT)"
                ),
            ]
        for statement in ddl:
            self._exec(statement)

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        params = tuple(params)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
                if cur.description:
                    rows = [dict(r) for r in cur.fetchall()]
                else:
                    rows = []
                    self._conn.commit()
            finally:
                cur.close()
        _log(sql, params, len(rows), self.backend, self.db_name)
        return rows

    def close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        finally:
            self._conn = None
            handle = self._handle
            self._handle = None
            if handle is not None:
                close = getattr(handle, "close", None)
                if callable(close):
                    close()
                elif getattr(self, "_seekdb", None) is not None:
                    self._seekdb.close(handle)

    # -- lore ------------------------------------------------------------------
    def count_lore(self) -> int:
        return int(self._exec("SELECT COUNT(*) AS n FROM lore")[0]["n"])

    def seed_lore(self, force: bool = False) -> int:
        if force:
            self._exec("DELETE FROM lore")
        if self.count_lore() and not force:
            return 0
        cards = json.loads((Path(__file__).parent / "lore.json").read_text(encoding="utf-8"))
        sql = (
            "INSERT INTO lore (id, category, title, content, keywords, price) "
            f"VALUES ({self._ph},{self._ph},{self._ph},{self._ph},{self._ph},{self._ph})"
        )
        for card in cards:
            self._exec(
                sql,
                (
                    card["id"],
                    card["category"],
                    card["title"],
                    card["content"],
                    card["keywords"],
                    card.get("price", 0),
                ),
            )
        return len(cards)

    def lore_cards(self, category: str | None = None) -> List[Dict[str, Any]]:
        if category:
            return self._exec(
                f"SELECT * FROM lore WHERE category = {self._ph} ORDER BY id", (category,)
            )
        return self._exec("SELECT * FROM lore ORDER BY id")

    def match_lore(self, message: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Rank lore cards by keyword hits; the card table itself lives in seekdb."""
        cards = self.lore_cards()
        scored: List[tuple[int, Dict[str, Any]]] = []
        for card in cards:
            keywords = [k for k in str(card.get("keywords") or "").split(",") if k]
            score = sum(1 for kw in keywords if kw and kw in message)
            if card["title"] in message:
                score += 2
            if score:
                scored.append((score, card))
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        hits = [card for _, card in scored[:limit]]
        if len(hits) < limit:
            # Fill with a deterministic "today's special" so the tavern always
            # has something to talk about, even for a plain greeting.
            drinks = [c for c in cards if c["category"] == "drink"]
            rumors = [c for c in cards if c["category"] == "rumor"]
            seed = zlib.crc32(message.encode("utf-8"))
            pool = [drinks[seed % len(drinks)]] if drinks else []
            if rumors:
                pool.append(rumors[(seed // 7) % len(rumors)])
            for card in pool:
                if card not in hits:
                    hits.append(card)
                if len(hits) >= limit:
                    break
        return hits

    def daily_special(self, seed_text: str) -> Dict[str, Any] | None:
        drinks = self.lore_cards("drink")
        if not drinks:
            return None
        return drinks[zlib.crc32(seed_text.encode("utf-8")) % len(drinks)]

    # -- players ---------------------------------------------------------------
    def get_player(self, player_id: str) -> Dict[str, Any]:
        rows = self._exec(
            f"SELECT * FROM players WHERE player_id = {self._ph}", (player_id,)
        )
        if rows:
            return rows[0]
        self._exec(
            "INSERT INTO players (player_id, epoch, visits, debt, grudge, memo) "
            f"VALUES ({self._ph}, 0, 0, 0, 0, '')",
            (player_id,),
        )
        return self._exec(
            f"SELECT * FROM players WHERE player_id = {self._ph}", (player_id,)
        )[0]

    def update_player(self, player_id: str, **fields: Any) -> Dict[str, Any]:
        if not fields:
            return self.get_player(player_id)
        assignments = ", ".join(f"{key} = {self._ph}" for key in fields)
        params = list(fields.values()) + [player_id]
        self._exec(
            f"UPDATE players SET {assignments} WHERE player_id = {self._ph}", params
        )
        return self.get_player(player_id)

    def set_scope(self, player_id: str, scope_id: str) -> None:
        self.update_player(player_id, pc_scope_id=scope_id)

    def reset_player(self, player_id: str) -> Dict[str, Any]:
        self._exec(
            "UPDATE players SET epoch = epoch + 1, pc_scope_id = NULL, visits = 0, "
            "debt = 0, grudge = 0, memo = '', last_seen = NULL "
            f"WHERE player_id = {self._ph}",
            (player_id,),
        )
        self._exec(f"DELETE FROM turns WHERE player_id = {self._ph}", (player_id,))
        return self.get_player(player_id)

    def add_turn(
        self,
        *,
        player_id: str,
        epoch: int,
        message: str,
        reply: str,
        intent: str,
        delta_debt: int,
        delta_grudge: int,
    ) -> None:
        self._exec(
            "INSERT INTO turns (player_id, epoch, ts, message, reply, intent, "
            f"delta_debt, delta_grudge) VALUES ({self._ph},{self._ph},{self._ph},"
            f"{self._ph},{self._ph},{self._ph},{self._ph},{self._ph})",
            (player_id, epoch, _now(), message, reply, intent, delta_debt, delta_grudge),
        )

    def recent_turns(self, player_id: str, epoch: int, limit: int = 5) -> List[Dict[str, Any]]:
        return self._exec(
            "SELECT ts, message, reply, intent, delta_debt, delta_grudge FROM turns "
            f"WHERE player_id = {self._ph} AND epoch = {self._ph} "
            f"ORDER BY id DESC LIMIT {int(limit)}",
            (player_id, epoch),
        )
