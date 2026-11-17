"""把 seekdb 里的台账与样例纪要导出成展示站可直接加载的 JSON。

运行：
    bash run.sh scripts/export_site_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import ledger  # noqa: E402

PROJECT = "Aurora"
OUT = PROJECT_ROOT / "site" / "data"
SAMPLES = PROJECT_ROOT / "data" / "samples"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    entries = ledger.load(project=PROJECT)
    items = [
        {
            "id": entry.id,
            "kind": entry.kind,
            "title": entry.title,
            "detail": entry.detail,
            "owner": entry.owner,
            "due": entry.due,
            "status": entry.status,
            "source": entry.source,
        }
        for entry in entries
    ]
    (OUT / "ledger.json").write_text(
        json.dumps({"project": PROJECT, "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    meetings = []
    for path in sorted(SAMPLES.glob("meeting-*.md")):
        meetings.append({"id": path.stem, "name": path.name, "text": path.read_text(encoding="utf-8")})
    (OUT / "meetings.json").write_text(
        json.dumps({"meetings": meetings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"台账 {len(items)} 条 → {OUT / 'ledger.json'}")
    print(f"纪要 {len(meetings)} 份 → {OUT / 'meetings.json'}")


if __name__ == "__main__":
    main()
