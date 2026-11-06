import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace(kind: str, payload: dict[str, Any], data_dir: str | None = None) -> dict[str, Any]:
    base = Path(data_dir or os.environ.get("DATA_DIR", "/data"))
    base.mkdir(parents=True, exist_ok=True)
    record = {"ts": utc_now(), "kind": kind, **payload}
    with _lock:
        with (base / f"{kind}_trace.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
