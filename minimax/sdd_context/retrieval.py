from __future__ import annotations

import re
from typing import Any

from .evidence import sha256_json, sha256_text, utc_now
from .models import ContextBundle, ContextItem, TaskState
from .store import SeekDBStore

WORD_RE = re.compile(r"[A-Za-z0-9_]+")
CJK_RE = re.compile(r"[一-鿿]+")
REQ_RE = re.compile(r"\b([RC]\d+)\b", re.IGNORECASE)


def extract_keywords(task: str, extra: list[str] | None = None) -> list[str]:
    text = " ".join([task, *(extra or [])])
    terms: list[str] = []

    for requirement in REQ_RE.findall(text):
        terms.append(requirement.upper())
    for word in WORD_RE.findall(text):
        if len(word) >= 2:
            terms.append(word.lower())
    for run in CJK_RE.findall(text):
        if len(run) >= 2:
            terms.append(run)
        for size in (2, 3):
            for index in range(max(0, len(run) - size + 1)):
                terms.append(run[index : index + size])
    return list(dict.fromkeys(terms))


def default_task_id(task: str) -> str:
    return f"task-{sha256_text(task.strip())[:12]}"


def _hash_bundle(task: str, items: list[ContextItem]) -> str:
    payload = {
        "task": task,
        "items": sorted(
            f"{item.kind}:{item.id}:{item.metadata.get('content_hash', '')}" for item in items
        ),
    }
    return sha256_json(payload)


def build_bundle(
    store: SeekDBStore,
    task: str,
    *,
    task_id: str | None = None,
    state: TaskState | None = None,
    limit: int = 6,
    extra_keywords: list[str] | None = None,
) -> ContextBundle:
    keywords = extract_keywords(task, extra_keywords)
    log_start = len(store.query_log)

    specs = store.search(keywords, "spec", limit)
    code = store.search(keywords, "code", limit)
    tests = store.search(keywords, "test", limit)

    bundle = ContextBundle(
        task=task,
        task_id=task_id or default_task_id(task),
        generated_at=utc_now(),
        specs=specs,
        code=code,
        tests=tests,
        state=state,
        db_queries=store.query_log[log_start:],
    )
    bundle.context_hash = _hash_bundle(task, [*specs, *code, *tests])
    return bundle


def summarize_bundle(bundle: ContextBundle) -> dict[str, Any]:
    return {
        "task": bundle.task,
        "task_id": bundle.task_id,
        "generated_at": bundle.generated_at,
        "context_hash": bundle.context_hash,
        "counts": {
            "specs": len(bundle.specs),
            "code": len(bundle.code),
            "tests": len(bundle.tests),
        },
        "sources": [
            {
                "kind": item.kind,
                "path": item.path,
                "symbol": item.symbol,
                "lines": [item.line_start, item.line_end],
                "score": item.score,
                "reasons": item.reasons,
            }
            for item in [*bundle.specs, *bundle.code, *bundle.tests]
        ],
        "db_query_count": len(bundle.db_queries),
        "state_reused": bundle.state is not None,
    }
