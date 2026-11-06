from __future__ import annotations

import time

from .powercontext import PowerContextClient
from .seekdb_store import SeekDBStore


class SearchService:
    def __init__(self, store: SeekDBStore, powercontext: PowerContextClient) -> None:
        self.store = store
        self.powercontext = powercontext

    def search(
        self,
        project_id: str,
        query: str,
        keyword: str | None = None,
        year_min: int | None = None,
        venue: str | None = None,
        n_results: int = 8,
        memory_enabled: bool = True,
        user_name: str = "anonymous",
    ) -> dict:
        started = time.perf_counter()
        project = self.store.get_project(project_id)
        scope_id = (project or {}).get("scope_id")

        memories: list[dict] = []
        memory_context = ""
        if memory_enabled and scope_id:
            try:
                memories = self.powercontext.search_memory(scope_id, query, limit=5)
                memory_context = self.powercontext.prepare(scope_id, query, max_bytes=3000)
            except Exception:  # noqa: BLE001 - memory is an enhancement, not a hard dependency
                memories = []
                memory_context = ""

        hits = self.store.search(
            project_id=project_id,
            query=query,
            n_results=n_results,
            keyword=keyword,
            year_min=year_min,
            venue=venue,
        )

        grouped: dict[str, dict] = {}
        for hit in hits:
            metadata = hit.get("metadata") or {}
            paper_id = metadata.get("paper_id") or "unknown"
            entry = grouped.get(paper_id)
            chunk = {
                "id": hit.get("id"),
                "text": hit.get("text", ""),
                "distance": hit.get("distance"),
                "section": metadata.get("section"),
                "page": metadata.get("page"),
            }
            if entry is None:
                grouped[paper_id] = {
                    "paper_id": paper_id,
                    "title": metadata.get("title", "Untitled"),
                    "authors": metadata.get("authors", ""),
                    "year": metadata.get("year"),
                    "venue": metadata.get("venue", ""),
                    "arxiv_id": metadata.get("arxiv_id", ""),
                    "snippet": chunk["text"][:420],
                    "chunks": [chunk],
                }
            else:
                entry["chunks"].append(chunk)

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self.store.log_event(
            project_id,
            action="search",
            query=query,
            latency_ms=int(latency_ms),
            result_count=len(grouped),
            user_name=user_name,
        )
        return {
            "query": query,
            "keyword": keyword,
            "year_min": year_min,
            "venue": venue,
            "memory_enabled": memory_enabled,
            "used_memories": memories,
            "memory_context": memory_context,
            "latency_ms": latency_ms,
            "results": list(grouped.values()),
        }
