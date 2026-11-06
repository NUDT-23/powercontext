from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, List, Sequence, Union

import httpx

from .config import Settings

Documents = Union[str, Sequence[str]]
Embeddings = List[List[float]]


class OpenAIEmbeddingFunction:
    """pyseekdb embedding function backed by any OpenAI-compatible /embeddings API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int,
        cache_path: Path,
        batch_size: int = 64,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._dimension = int(dimension)
        self.batch_size = max(1, int(batch_size))
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: sqlite3.Connection | None = None

    @property
    def dimension(self) -> int:
        return self._dimension

    def _conn(self) -> sqlite3.Connection:
        if self._cache is None:
            self._cache = sqlite3.connect(str(self.cache_path), check_same_thread=False)
            self._cache.execute(
                "CREATE TABLE IF NOT EXISTS emb_cache (key TEXT PRIMARY KEY, vector TEXT NOT NULL)"
            )
            self._cache.commit()
        return self._cache

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\x00{text}".encode("utf-8")).hexdigest()

    def _load_cached(self, texts: Sequence[str]) -> dict[str, List[float]]:
        conn = self._conn()
        found: dict[str, List[float]] = {}
        with self._lock:
            for text in texts:
                key = self._key(text)
                row = conn.execute("SELECT vector FROM emb_cache WHERE key = ?", (key,)).fetchone()
                if row:
                    found[key] = json.loads(row[0])
        return found

    def _store_cached(self, items: dict[str, List[float]]) -> None:
        conn = self._conn()
        with self._lock:
            conn.executemany(
                "INSERT OR REPLACE INTO emb_cache (key, vector) VALUES (?, ?)",
                [(key, json.dumps(vector)) for key, vector in items.items()],
            )
            conn.commit()

    def _request_embeddings(self, texts: Sequence[str]) -> List[List[float]]:
        payload = {"model": self.model, "input": list(texts)}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{self.base_url}/embeddings", json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Embedding API failed ({response.status_code}): {response.text[:500]}"
            )
        body = response.json()
        data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Embedding API returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        for vector in vectors:
            if len(vector) != self._dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch: expected {self._dimension}, got {len(vector)}. "
                    "Update EMBEDDING_DIM or rebuild the seekdb collection."
                )
        return vectors

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        cached = self._load_cached(texts)
        results: List[List[float] | None] = [None] * len(texts)
        missing_texts: list[str] = []
        missing_indexes: list[int] = []
        for index, text in enumerate(texts):
            vector = cached.get(self._key(text))
            if vector is not None:
                results[index] = vector
            else:
                missing_texts.append(text)
                missing_indexes.append(index)

        for start in range(0, len(missing_texts), self.batch_size):
            batch = missing_texts[start : start + self.batch_size]
            vectors = self._request_embeddings(batch)
            cache_items = {}
            for offset, (text, vector) in enumerate(zip(batch, vectors)):
                key = self._key(text)
                results[missing_indexes[start + offset]] = vector
                cache_items[key] = vector
            self._store_cached(cache_items)

        return [vector for vector in results if vector is not None]

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 - pyseekdb protocol
        single = isinstance(input, str)
        texts = [input] if single else list(input)
        if not texts:
            return []
        vectors = self._embed(texts)
        return vectors


class LocalEmbeddingFunction:
    """Lazy wrapper around pyseekdb's default all-MiniLM-L6-v2 embedding."""

    def __init__(self) -> None:
        from pyseekdb import DefaultEmbeddingFunction

        self._inner = DefaultEmbeddingFunction()

    @property
    def dimension(self) -> int:
        return int(self._inner.dimension)

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002
        return self._inner(input)


def build_embedding_function(settings: Settings) -> tuple[object, str]:
    provider = settings.embedding_provider.strip().lower()
    if provider == "auto":
        provider = "openai" if settings.openai_api_key.strip() else "local"

    if provider == "openai":
        if not settings.openai_api_key.strip():
            raise RuntimeError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is empty")
        function = OpenAIEmbeddingFunction(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dim,
            cache_path=settings.data_path / "embedding_cache.sqlite3",
            batch_size=settings.embedding_batch_size,
        )
        return function, f"openai:{settings.embedding_model}"

    function = LocalEmbeddingFunction()
    return function, "local:all-MiniLM-L6-v2"
