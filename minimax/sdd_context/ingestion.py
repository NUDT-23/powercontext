from __future__ import annotations

from typing import Any

from .chunking import iter_project_docs
from .config import Settings
from .evidence import utc_now, write_json
from .store import SeekDBStore


def open_store(settings: Settings) -> SeekDBStore:
    return SeekDBStore(settings.db_path, settings.db_name, settings.collection)


def ingest(settings: Settings, *, record: bool = True) -> dict[str, Any]:
    docs = iter_project_docs(settings.project_dir)
    store = open_store(settings)
    upserted = store.upsert(docs)
    pruned = store.prune({doc.id for doc in docs})
    stats = store.stats()

    kinds: dict[str, int] = {}
    for doc in docs:
        kinds[doc.kind] = kinds.get(doc.kind, 0) + 1

    result: dict[str, Any] = {
        "generated_at": utc_now(),
        "project_dir": str(settings.project_dir),
        "db_path": str(settings.db_path),
        "database": settings.db_name,
        "collection": settings.collection,
        "documents": len(docs),
        "by_kind": dict(sorted(kinds.items())),
        "upserted": upserted,
        "pruned": pruned,
        "stats": stats,
        "sources": [
            {
                "id": doc.id,
                "kind": doc.kind,
                "path": doc.path,
                "symbol": doc.symbol,
                "line_start": doc.line_start,
                "line_end": doc.line_end,
                "content_hash": doc.content_hash,
            }
            for doc in docs
        ],
    }
    if record:
        write_json(settings.artifacts_dir / "run" / "ingest.json", result)
    return result
