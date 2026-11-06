from __future__ import annotations

import threading
from typing import Any, Sequence

from pyseekdb.client.sql_utils import render_sql_with_params


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        research_question TEXT,
        scope_id VARCHAR(128),
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS papers (
        id VARCHAR(64) PRIMARY KEY,
        project_id VARCHAR(64) NOT NULL,
        title VARCHAR(512) NOT NULL,
        authors TEXT,
        year INT,
        venue VARCHAR(255),
        arxiv_id VARCHAR(64),
        abstract TEXT,
        source VARCHAR(64),
        read_status INT NOT NULL DEFAULT 0,
        added_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        project_id VARCHAR(64),
        user_name VARCHAR(128),
        action VARCHAR(64) NOT NULL,
        query TEXT,
        latency_ms INT,
        result_count INT,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        project_id VARCHAR(64),
        user_name VARCHAR(128),
        paper_id VARCHAR(64),
        rating INT,
        relevant TINYINT,
        comment TEXT,
        created_at DATETIME NOT NULL
    )
    """,
]


class Database:
    """Parameterized SQL helper over the embedded seekdb connection.

    pylibseekdb's cursor only accepts a rendered SQL string, so parameters are
    escaped with pyseekdb's own ``render_sql_with_params`` helper.
    """

    def __init__(self, client: Any, lock: threading.RLock | None = None) -> None:
        self.client = client
        # The embedded client exposes a single connection and FastAPI runs sync
        # endpoints in a threadpool, so every SQL call must be serialized.
        self.lock = lock or threading.RLock()

    def _raw(self) -> Any:
        return self.client.get_raw_connection()

    def init_schema(self) -> None:
        for statement in SCHEMA:
            self.execute(statement)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.lock:
            return self.client._execute_query_with_cursor(
                self._raw(), sql, list(params), use_context_manager=False
            )

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        rendered = render_sql_with_params(sql, tuple(params))
        with self.lock:
            connection = self._raw()
            cursor = connection.cursor()
            try:
                cursor.execute(rendered)
                return int(getattr(cursor, "lastrowid", 0) or 0)
            finally:
                cursor.close()

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        rows = self.query(sql, params)
        if not rows:
            return None
        return next(iter(rows[0].values()))
