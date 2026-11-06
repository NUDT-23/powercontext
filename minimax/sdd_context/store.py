from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pyseekdb

from .evidence import utc_now
from .models import ContextItem, SourceDoc


class HashEmbeddingFunction:
    """Deterministic offline embedding: signed hashing over words and CJK n-grams."""

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        for run in re.findall(r"[一-鿿]+", text):
            for size in (2, 3):
                for index in range(max(0, len(run) - size + 1)):
                    tokens.append(run[index : index + size])
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            position = int.from_bytes(digest[:4], "big") % self._dimension
            vector[position] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def __call__(self, input: Any) -> list[list[float]]:
        texts = [input] if isinstance(input, str) else list(input)
        return [self._embed(text) for text in texts]


def _flat(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return value[0]
        return value
    return [value]


def _rows_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = _flat(result.get("ids"))
    documents = _flat(result.get("documents"))
    metadatas = _flat(result.get("metadatas"))
    rows = []
    for index, row_id in enumerate(ids):
        rows.append(
            {
                "id": row_id,
                "document": documents[index] if index < len(documents) else "",
                "metadata": metadatas[index] if index < len(metadatas) and metadatas[index] else {},
            }
        )
    return rows


def _excerpt(text: str, keywords: list[str], width: int = 360) -> str:
    lowered = text.lower()
    position = -1
    for keyword in sorted(keywords, key=len, reverse=True):
        found = lowered.find(keyword.lower())
        if found != -1 and (position == -1 or found < position):
            position = found
    if position == -1:
        snippet = text[:width]
    else:
        start = max(0, position - width // 3)
        snippet = text[start : start + width]
    snippet = snippet.replace("\r", " ").replace("\n", " ").strip()
    return snippet


class SeekDBStore:
    def __init__(self, db_path: Path, db_name: str, collection_name: str) -> None:
        self.db_path = db_path
        self.db_name = db_name
        self.collection_name = collection_name
        self.query_log: list[dict[str, Any]] = []
        self._rows: list[dict[str, Any]] | None = None
        self.db_path.mkdir(parents=True, exist_ok=True)
        self._ensure_database()
        self.client = pyseekdb.Client(path=str(self.db_path), database=db_name)
        self.embedding = HashEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            collection_name, embedding_function=self.embedding
        )

    def _ensure_database(self) -> None:
        admin = pyseekdb.AdminClient(path=str(self.db_path))
        names: set[str] = set()
        try:
            for database in admin.list_databases():
                name = getattr(database, "name", None)
                if name is None and isinstance(database, dict):
                    name = database.get("name")
                if name:
                    names.add(str(name))
        except Exception:
            names = set()
        if self.db_name not in names:
            try:
                admin.create_database(self.db_name)
            except Exception as exc:
                if "exist" not in str(exc).lower():
                    raise

    def upsert(self, docs: list[SourceDoc]) -> int:
        if not docs:
            return 0
        self.collection.upsert(
            ids=[doc.id for doc in docs],
            documents=[doc.document_text() for doc in docs],
            metadatas=[doc.to_metadata() for doc in docs],
        )
        self.collection.refresh_index()
        self._rows = None
        return len(docs)

    def all_rows(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = _rows_from_result(self.collection.peek(limit=10000))
        return self._rows

    def stats(self) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for row in self.all_rows():
            counts[str(row["metadata"].get("kind", "unknown"))] += 1
        return {
            "db_path": str(self.db_path),
            "database": self.db_name,
            "collection": self.collection_name,
            "total": len(self.all_rows()),
            "by_kind": dict(sorted(counts.items())),
        }

    def dominant_component(self, keywords: Iterable[str]) -> str | None:
        scores: dict[str, int] = defaultdict(int)
        terms = [keyword.lower() for keyword in keywords]
        for row in self.all_rows():
            component = str(row["metadata"].get("component", ""))
            if not component:
                continue
            text = str(row.get("document") or "").lower()
            scores[component] += sum(1 for term in terms if term in text)
        if not scores:
            return None
        component, score = max(scores.items(), key=lambda item: item[1])
        return component if score > 0 else None

    def _log(self, method: str, kind: str, params: dict[str, Any], rows: list[Any]) -> None:
        self.query_log.append(
            {"ts": utc_now(), "method": method, "kind": kind, "params": params, "result_ids": list(rows)}
        )

    def search(
        self,
        keywords: list[str],
        kind: str,
        limit: int = 10,
        component: str | None = None,
    ) -> list[ContextItem]:
        terms = [term for term in dict.fromkeys(keywords) if len(term) >= 2][:24]
        rows = {row["id"]: row for row in self.all_rows()}
        if not terms or not rows:
            return []

        hits: dict[str, int] = defaultdict(int)
        reasons: dict[str, list[str]] = defaultdict(list)
        vector_score: dict[str, float] = defaultdict(float)
        req_boost: dict[str, float] = defaultdict(float)

        for term in terms:
            try:
                result = self.collection.get(
                    where={"kind": kind}, where_document={"$contains": term}
                )
            except Exception as exc:
                self.query_log.append(
                    {"ts": utc_now(), "method": "get", "kind": kind, "params": {"$contains": term}, "error": str(exc)}
                )
                continue
            found = _flat(result.get("ids"))
            self._log("get", kind, {"where": {"kind": kind}, "where_document": {"$contains": term}}, found)
            for row_id in found:
                if row_id in rows:
                    hits[row_id] += 1
                    reasons[row_id].append(f"keyword:{term}")

        if terms:
            try:
                result = self.collection.query(
                    query_texts=[" ".join(terms)],
                    n_results=max(limit * 3, 12),
                    where={"kind": kind},
                )
            except TypeError:
                try:
                    result = self.collection.query(
                        query_texts=[" ".join(terms)], n_results=max(limit * 3, 12)
                    )
                except Exception as exc:
                    result = None
                    self.query_log.append(
                        {"ts": utc_now(), "method": "query", "kind": kind, "params": {"query_text": " ".join(terms)}, "error": str(exc)}
                    )
            except Exception as exc:
                result = None
                self.query_log.append(
                    {"ts": utc_now(), "method": "query", "kind": kind, "params": {"query_text": " ".join(terms)}, "error": str(exc)}
                )
            if result is not None:
                found = _flat(result.get("ids"))
                distances = _flat(result.get("distances"))
                self._log(
                    "query",
                    kind,
                    {"query_text": " ".join(terms), "n_results": max(limit * 3, 12)},
                    found,
                )
                for rank, row_id in enumerate(found):
                    if row_id not in rows:
                        continue
                    if rows[row_id]["metadata"].get("kind") != kind:
                        continue
                    vector_score[row_id] = max(vector_score[row_id], 1.0 / (rank + 1))
                    reasons[row_id].append("vector")

        dominant = component or self.dominant_component(terms)
        for row_id, row in rows.items():
            if row["metadata"].get("kind") != kind:
                continue
            if dominant and row["metadata"].get("component") == dominant:
                hits[row_id] = max(hits[row_id], 1)
                if f"component:{dominant}" not in reasons[row_id]:
                    reasons[row_id].append(f"component:{dominant}")

        requirement_terms = {term.upper() for term in terms if re.fullmatch(r"[RC]\d+", term, re.IGNORECASE)}
        if requirement_terms:
            for row_id, row in rows.items():
                if row["metadata"].get("kind") != kind:
                    continue
                declared = set(
                    filter(None, str(row["metadata"].get("requirement_ids") or row["metadata"].get("covers") or "").split(","))
                )
                if declared & requirement_terms:
                    req_boost[row_id] = 3.0
                    reasons[row_id].append(f"requirement:{','.join(sorted(declared & requirement_terms))}")

        scored: list[tuple[float, str]] = []
        for row_id in set(hits) | set(vector_score) | set(req_boost):
            score = 2.0 * hits[row_id] + vector_score[row_id] + req_boost[row_id]
            scored.append((score, row_id))
        scored.sort(key=lambda item: (-item[0], item[1]))

        items: list[ContextItem] = []
        for score, row_id in scored[:limit]:
            row = rows[row_id]
            metadata = dict(row["metadata"])
            items.append(
                ContextItem(
                    id=row_id,
                    kind=str(metadata.get("kind", kind)),
                    path=str(metadata.get("path", "")),
                    symbol=str(metadata.get("symbol", "")),
                    heading=str(metadata.get("heading", "")),
                    line_start=int(metadata.get("line_start", 0)),
                    line_end=int(metadata.get("line_end", 0)),
                    excerpt=_excerpt(str(row.get("document") or ""), terms),
                    score=round(score, 3),
                    reasons=list(dict.fromkeys(reasons.get(row_id, []))),
                    metadata=metadata,
                )
            )
        return items

    def prune(self, valid_ids: set[str]) -> int:
        existing = [row["id"] for row in self.all_rows()]
        stale = [row_id for row_id in existing if row_id not in valid_ids]
        if stale:
            self.collection.delete(ids=stale)
            self.collection.refresh_index()
            self._rows = None
        return len(stale)
