from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import pyseekdb
from pyseekdb.client.client_seekdb_embedded import SeekdbEmbeddedClient

from .config import Settings
from .db import Database
from .tracing import trace


def now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return uuid.uuid4().hex[:24]


class SeekDBStore:
    def __init__(self, settings: Settings, embedding_function: Any) -> None:
        self.settings = settings
        self.embedding_function = embedding_function
        admin = pyseekdb.AdminClient(path=str(settings.seekdb_path))
        admin.create_database(settings.seekdb_database)
        # The high-level Client is a proxy that hides the raw SQL connection,
        # so use the embedded client directly for both SQL and collection access.
        self.client = SeekdbEmbeddedClient(
            path=str(settings.seekdb_path),
            database=settings.seekdb_database,
        )
        self.lock = threading.RLock()
        self.db = Database(self.client, self.lock)
        try:
            self.collection = self.client.get_or_create_collection(
                name=settings.collection_name,
                embedding_function=embedding_function,
                distance="cosine",
            )
        except TypeError:
            self.collection = self.client.get_or_create_collection(
                name=settings.collection_name,
                embedding_function=embedding_function,
            )
        self._validate_dimension()

    def _validate_dimension(self) -> None:
        existing = getattr(self.collection, "dimension", None)
        expected = getattr(self.embedding_function, "dimension", None)
        if existing and expected and int(existing) != int(expected):
            raise RuntimeError(
                f"seekdb collection dimension is {existing}, embedding function produces {expected}. "
                "Keep EMBEDDING_MODEL/EMBEDDING_DIM stable or re-create the collection and re-seed."
            )

    def init_schema(self) -> None:
        self.db.init_schema()

    # ---------- projects ----------

    def create_project(
        self,
        name: str,
        description: str = "",
        research_question: str = "",
        project_id: str | None = None,
    ) -> dict:
        pid = project_id or new_id()
        timestamp = now_sql()
        self.db.execute(
            "INSERT INTO projects (id, name, description, research_question, scope_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (pid, name, description, research_question, None, timestamp, timestamp),
        )
        return self.get_project(pid) or {}

    def set_scope(self, project_id: str, scope_id: str) -> None:
        self.db.execute(
            "UPDATE projects SET scope_id = %s, updated_at = %s WHERE id = %s",
            (scope_id, now_sql(), project_id),
        )

    def get_project(self, project_id: str) -> dict | None:
        rows = self.db.query(
            "SELECT id, name, description, research_question, scope_id, created_at, updated_at "
            "FROM projects WHERE id = %s",
            (project_id,),
        )
        return rows[0] if rows else None

    def list_projects(self) -> list[dict]:
        return self.db.query(
            "SELECT id, name, description, research_question, scope_id, created_at, updated_at "
            "FROM projects ORDER BY created_at DESC"
        )

    # ---------- papers ----------

    def paper_exists(self, project_id: str, arxiv_id: str) -> bool:
        rows = self.db.query(
            "SELECT id FROM papers WHERE project_id = %s AND arxiv_id = %s LIMIT 1",
            (project_id, arxiv_id),
        )
        return bool(rows)

    def add_paper(self, project_id: str, paper: dict, chunks: list[dict]) -> dict:
        paper_id = new_id()
        timestamp = now_sql()
        self.db.execute(
            "INSERT INTO papers "
            "(id, project_id, title, authors, year, venue, arxiv_id, abstract, source, read_status, added_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                paper_id,
                project_id,
                paper.get("title", "Untitled")[:500],
                paper.get("authors", ""),
                int(paper.get("year") or 0) or None,
                paper.get("venue", ""),
                paper.get("arxiv_id", ""),
                paper.get("abstract", ""),
                paper.get("source", "manual"),
                0,
                timestamp,
            ),
        )

        ids = [f"{paper_id}#{index}" for index in range(len(chunks))]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [
            {
                "paper_id": paper_id,
                "project_id": project_id,
                "title": paper.get("title", "Untitled")[:500],
                "authors": paper.get("authors", "")[:500],
                "year": int(paper.get("year") or 0),
                "venue": (paper.get("venue") or "")[:200],
                "arxiv_id": paper.get("arxiv_id", ""),
                "section": chunk.get("section", "body")[:100],
                "page": int(chunk.get("page") or 0),
                "read_status": 0,
            }
            for chunk in chunks
        ]
        if ids:
            try:
                with self.lock:
                    self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
            except Exception:
                # Roll back the metadata row to avoid a paper with no searchable chunks.
                self.db.execute("DELETE FROM papers WHERE id = %s", (paper_id,))
                raise
        return self.get_paper(paper_id) or {}

    PAPERS_COLUMNS = (
        "id, project_id, title, authors, year, venue, arxiv_id, abstract, "
        "source, read_status, added_at"
    )

    def get_paper(self, paper_id: str) -> dict | None:
        rows = self.db.query(
            f"SELECT {self.PAPERS_COLUMNS} FROM papers WHERE id = %s", (paper_id,)
        )
        return rows[0] if rows else None

    def list_papers(self, project_id: str) -> list[dict]:
        return self.db.query(
            f"SELECT {self.PAPERS_COLUMNS} FROM papers WHERE project_id = %s "
            "ORDER BY added_at DESC, title ASC",
            (project_id,),
        )

    def get_papers_by_ids(self, paper_ids: list[str]) -> list[dict]:
        if not paper_ids:
            return []
        placeholders = ", ".join(["%s"] * len(paper_ids))
        return self.db.query(
            f"SELECT {self.PAPERS_COLUMNS} FROM papers WHERE id IN ({placeholders})",
            tuple(paper_ids),
        )

    def update_read_status(self, paper_id: str, read_status: int) -> None:
        self.db.execute(
            "UPDATE papers SET read_status = %s WHERE id = %s",
            (int(read_status), paper_id),
        )

    def count_papers(self, project_id: str) -> int:
        value = self.db.scalar("SELECT COUNT(*) FROM papers WHERE project_id = %s", (project_id,))
        return int(value or 0)

    def count_chunks(self, project_id: str) -> int:
        try:
            with self.lock:
                result = self.collection.get(where={"project_id": project_id}, limit=2000)
        except Exception:  # noqa: BLE001
            return 0
        ids = result.get("ids") or []
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        return len(ids)

    # ---------- retrieval ----------

    def search(
        self,
        project_id: str,
        query: str,
        n_results: int = 8,
        keyword: str | None = None,
        year_min: int | None = None,
        venue: str | None = None,
    ) -> list[dict]:
        where: dict[str, Any] = {"project_id": project_id}
        if year_min:
            where["year"] = {"$gte": int(year_min)}
        if venue:
            where["venue"] = {"$eq": venue}

        candidate_count = max(20, n_results * 3)
        text_query: dict[str, Any] = {"where": where, "n_results": candidate_count}
        if keyword:
            text_query["where_document"] = {"$contains": keyword}
        vector_query: dict[str, Any] = {
            "query_texts": [query],
            "where": where,
            "n_results": candidate_count,
        }

        started = time.perf_counter()
        mode = "hybrid"
        error = None
        try:
            with self.lock:
                result = self.collection.hybrid_search(
                    query=text_query,
                    knn=vector_query,
                    rank={"rrf": {}},
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )
        except Exception as exc:  # noqa: BLE001 - degrade to vector search
            mode = "fallback_vector"
            error = f"{type(exc).__name__}: {exc}"
            query_kwargs: dict[str, Any] = {
                "query_texts": [query],
                "where": where,
                "n_results": n_results,
                "include": ["documents", "metadatas", "distances"],
            }
            if keyword:
                query_kwargs["where_document"] = {"$contains": keyword}
            with self.lock:
                result = self.collection.query(**query_kwargs)

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[dict] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            hits.append(
                {
                    "id": chunk_id,
                    "text": documents[index] if index < len(documents) else "",
                    "metadata": metadata,
                    "distance": distances[index] if index < len(distances) else None,
                }
            )

        trace(
            "seekdb_search",
            {
                "project_id": project_id,
                "query": query,
                "keyword": keyword,
                "where": where,
                "mode": mode,
                "n_results": n_results,
                "latency_ms": latency_ms,
                "result_ids": [hit["id"] for hit in hits],
                "results": [
                    {
                        "id": hit["id"],
                        "paper_id": hit["metadata"].get("paper_id"),
                        "title": hit["metadata"].get("title"),
                        "distance": hit["distance"],
                    }
                    for hit in hits
                ],
                "error": error,
            },
            data_dir=self.settings.data_dir,
        )
        return hits

    def get_chunks_for_paper(self, paper_id: str, limit: int = 30) -> list[dict]:
        try:
            with self.lock:
                result = self.collection.get(
                    where={"paper_id": paper_id},
                    limit=limit,
                    include=["documents", "metadatas"],
                )
        except Exception:  # noqa: BLE001
            return []
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        if documents and isinstance(documents[0], list):
            documents = documents[0]
        if metadatas and isinstance(metadatas[0], list):
            metadatas = metadatas[0]
        chunks: list[dict] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            chunks.append(
                {
                    "id": chunk_id,
                    "text": documents[index] if index < len(documents) else "",
                    "section": metadata.get("section", "body"),
                    "page": metadata.get("page", 0),
                }
            )
        return chunks

    # ---------- usage ----------

    def log_event(
        self,
        project_id: str,
        action: str,
        query: str = "",
        latency_ms: int = 0,
        result_count: int = 0,
        user_name: str = "anonymous",
    ) -> None:
        self.db.execute(
            "INSERT INTO events (project_id, user_name, action, query, latency_ms, result_count, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (project_id, user_name, action, query[:1000], int(latency_ms), int(result_count), now_sql()),
        )

    def add_feedback(
        self,
        project_id: str,
        rating: int | None,
        relevant: int | None,
        comment: str,
        paper_id: str | None = None,
        user_name: str = "anonymous",
    ) -> None:
        self.db.execute(
            "INSERT INTO feedback (project_id, user_name, paper_id, rating, relevant, comment, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (project_id, user_name, paper_id, rating, relevant, comment[:2000], now_sql()),
        )

    def stats(self, project_id: str) -> dict:
        papers = self.count_papers(project_id)
        events = self.db.query(
            "SELECT action, COUNT(*) AS count, AVG(latency_ms) AS avg_latency_ms "
            "FROM events WHERE project_id = %s GROUP BY action",
            (project_id,),
        )
        feedback = self.db.query(
            "SELECT COUNT(*) AS count, AVG(rating) AS avg_rating "
            "FROM feedback WHERE project_id = %s",
            (project_id,),
        )
        users = self.db.query(
            "SELECT COUNT(DISTINCT user_name) AS users FROM events "
            "WHERE project_id = %s AND user_name IS NOT NULL AND user_name <> 'anonymous'",
            (project_id,),
        )
        recent = self.db.query(
            "SELECT action, query, latency_ms, result_count, created_at "
            "FROM events WHERE project_id = %s ORDER BY id DESC LIMIT 10",
            (project_id,),
        )
        return {
            "papers": papers,
            "users": int((users[0] or {}).get("users") or 0) if users else 0,
            "events": events,
            "feedback": feedback[0] if feedback else {"count": 0, "avg_rating": None},
            "recent_events": recent,
        }
