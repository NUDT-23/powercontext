from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class SourceDoc:
    id: str
    kind: str
    path: str
    symbol: str
    heading: str
    content: str
    line_start: int
    line_end: int
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def document_text(self) -> str:
        return f"[{self.kind}] {self.path} :: {self.heading}\n{self.content}"

    def to_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "path": self.path,
            "symbol": self.symbol,
            "heading": self.heading,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "content_hash": self.content_hash,
        }
        for key, value in self.metadata.items():
            if isinstance(value, (str, int, float, bool)):
                data[key] = value
            elif value is None:
                continue
            else:
                data[key] = json.dumps(value, ensure_ascii=False)
        return data


@dataclass
class ContextItem:
    id: str
    kind: str
    path: str
    symbol: str
    heading: str
    line_start: int
    line_end: int
    excerpt: str
    score: float
    reasons: list[str]
    metadata: dict[str, Any]


@dataclass
class TaskState:
    task_id: str
    task: str
    phase: str
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    context_hash: str = ""
    saved_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        known = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class ContextBundle:
    task: str
    task_id: str
    generated_at: str
    specs: list[ContextItem]
    code: list[ContextItem]
    tests: list[ContextItem]
    state: TaskState | None
    db_queries: list[dict[str, Any]]
    context_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def source_from_row(row: dict[str, Any]) -> SourceDoc:
    meta = dict(row.get("metadata") or {})
    text = row.get("document") or ""
    header, _, body = text.partition("\n")
    return SourceDoc(
        id=row["id"],
        kind=str(meta.get("kind", "")),
        path=str(meta.get("path", "")),
        symbol=str(meta.get("symbol", "")),
        heading=str(meta.get("heading", "")),
        content=body if header.startswith("[") else text,
        line_start=int(meta.get("line_start", 0)),
        line_end=int(meta.get("line_end", 0)),
        content_hash=str(meta.get("content_hash", "")),
        metadata=meta,
    )
