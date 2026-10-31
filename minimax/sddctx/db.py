"""Storage layer for engineering material (specs / code / tests).

Default backend is the embedded **seekdb** (``pylibseekdb`` + PyMySQL). A
``sqlite`` backend is provided only for offline local smoke tests; the demo and
the README use seekdb so the database genuinely participates.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Iterable, List

from . import config

ROWS: List[Dict[str, Any]] = []  # populated rows returned by the last query


def _log(
    sql: str, params: Iterable[Any], rows: int, backend: str, db_name: str
) -> None:
    config.ensure_dirs()
    line = (
        f"{_dt.datetime.now().isoformat(timespec='seconds')}\t"
        f"backend={backend}\tdb={db_name}\trows={rows}\t"
        f"params={list(params)!r}\tsql={sql.strip()}\n"
    )
    with (config.ARTIFACTS / "db_queries.log").open("a", encoding="utf-8") as fh:
        fh.write(line)


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[\s,;:()\[\]{}]+", text) if t]


class DocStore:
    def __init__(
        self,
        backend: str | None = None,
        path: str | None = None,
        db_name: str | None = None,
    ) -> None:
        self.backend = backend or config.DB_BACKEND
        self.path = path or str(config.DB_PATH)
        self.db_name = db_name or config.DB_NAME
        self._ph = "%s" if self.backend == "seekdb" else "?"
        self._conn = None
        self._handle = None
        self._open()

    # -- connection management -------------------------------------------------
    def _open(self) -> None:
        if self.backend == "sqlite":
            import sqlite3

            config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        elif self.backend == "seekdb":
            try:
                import pylibseekdb as seekdb  # type: ignore
                import pymysql
            except ImportError as exc:
                raise RuntimeError(
                    "seekdb backend needs pylibseekdb (Linux wheels) and pymysql; "
                    "install requirements.txt or set SDDCTX_DB_BACKEND=sqlite for local dev"
                ) from exc

            self._pymysql = pymysql
            self._seekdb = seekdb
            config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._handle = seekdb.open(self.path)
            opts = {
                key: value
                for key, value in dict(self._handle.connection_options()).items()
                if key not in ("database", "db") and value is not None
            }
            # Create the target database if it does not exist yet.
            bootstrap = pymysql.connect(**opts, autocommit=True)
            with bootstrap.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.db_name}` "
                    "DEFAULT CHARACTER SET utf8mb4"
                )
            bootstrap.close()
            self._conn = pymysql.connect(
                **opts, database=self.db_name, autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
        else:
            raise ValueError(f"unknown DB backend: {self.backend}")
        self._create_schema()

    def _create_schema(self) -> None:
        if self.backend == "sqlite":
            ddl = (
                "CREATE TABLE IF NOT EXISTS eng_docs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "path TEXT NOT NULL, kind TEXT NOT NULL, req_id TEXT,"
                "symbol TEXT, lineno INTEGER, text TEXT, hash TEXT)"
            )
        else:
            ddl = (
                "CREATE TABLE IF NOT EXISTS eng_docs ("
                "id BIGINT PRIMARY KEY AUTO_INCREMENT,"
                "path VARCHAR(512) NOT NULL, kind VARCHAR(32) NOT NULL,"
                "req_id VARCHAR(64), symbol VARCHAR(255), lineno INT,"
                "text MEDIUMTEXT, hash VARCHAR(64))"
            )
        self._exec(ddl)

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        params = tuple(params)
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

    # -- public API ------------------------------------------------------------
    def reset(self) -> None:
        self._exec("DELETE FROM eng_docs")

    def insert_many(self, docs: List[Dict[str, Any]]) -> int:
        sql = (
            "INSERT INTO eng_docs (path, kind, req_id, symbol, lineno, text, hash) "
            f"VALUES ({self._ph},{self._ph},{self._ph},{self._ph},{self._ph},{self._ph},{self._ph})"
        )
        for doc in docs:
            self._exec(
                sql,
                (
                    doc["path"], doc["kind"], doc.get("req_id"), doc.get("symbol"),
                    doc.get("lineno"), doc["text"], doc["hash"],
                ),
            )
        return len(docs)

    def count(self) -> int:
        return int(self._exec("SELECT COUNT(*) AS n FROM eng_docs")[0]["n"])

    def query(self, kind: str, keywords: List[str]) -> List[Dict[str, Any]]:
        """Return rows of ``kind`` that match any keyword (SQL LIKE), best first."""
        if not keywords:
            rows = self._exec("SELECT * FROM eng_docs WHERE kind=%s" % self._ph, (kind,))
        else:
            like = f"%{{}}%"
            clauses, params = [], []
            for kw in keywords:
                clauses.append(
                    f"(text LIKE {self._ph} OR path LIKE {self._ph} OR symbol LIKE {self._ph})"
                )
                params.extend([like.format(kw)] * 3)
            sql = (
                "SELECT * FROM eng_docs WHERE kind=%s AND (" % self._ph
                + " OR ".join(clauses) + ")"
            )
            rows = self._exec(sql, [kind, *params])

        lowered = [k.lower() for k in keywords]

        def score(row: Dict[str, Any]) -> int:
            hay = " ".join(
                str(row.get(k) or "") for k in ("text", "path", "symbol", "req_id")
            ).lower()
            return sum(hay.count(k) for k in lowered)

        rows.sort(key=score, reverse=True)
        global ROWS
        ROWS = rows
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
