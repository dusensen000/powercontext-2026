"""建库：Client 代理只暴露 collection 操作，库要走 AdminClient。"""
from __future__ import annotations

from pathlib import Path

import pyseekdb

from .config import (
    SEEKDB_DATABASE,
    SEEKDB_HOST,
    SEEKDB_PASSWORD,
    SEEKDB_PATH,
    SEEKDB_PORT,
    SEEKDB_USE_SERVER,
    SEEKDB_USER,
    ensure_seekdb_dir,
)


def ensure_database() -> None:
    if SEEKDB_USE_SERVER:
        admin = pyseekdb.AdminClient(
            host=SEEKDB_HOST, port=SEEKDB_PORT, user=SEEKDB_USER, password=SEEKDB_PASSWORD
        )
    else:
        ensure_seekdb_dir()
        admin = pyseekdb.AdminClient(path=str(SEEKDB_PATH))
    admin.create_database(SEEKDB_DATABASE)


if __name__ == "__main__":
    ensure_database()
    target = f"{SEEKDB_HOST}:{SEEKDB_PORT}" if SEEKDB_USE_SERVER else str(SEEKDB_PATH)
    print(f"[OK] database {SEEKDB_DATABASE} ready at {target}")
