from __future__ import annotations

import json
from typing import Any

from .models import TaskState
from .powercontext_client import PowerContextClient

STATE_KIND = "sdd-task-state"


def save_task_state(
    client: PowerContextClient,
    state: TaskState,
    *,
    scope_id: str | None = None,
) -> dict[str, Any]:
    scope = client.resolve_scope(scope_id)
    response = client.remember(
        scope,
        STATE_KIND,
        state.to_json(),
        description=f"{STATE_KIND}:{state.task_id}",
        reason="SDD task checkpoint",
    )
    records = response.get("records") or []
    record = records[0] if records else {}
    return {
        "scope_id": scope,
        "changed": response.get("changed"),
        "artifact": record.get("artifact"),
        "state_version": record.get("state_version"),
    }


def load_task_state(
    client: PowerContextClient,
    task_id: str,
    *,
    scope_id: str | None = None,
) -> tuple[TaskState | None, str, dict[str, Any] | None]:
    scope = client.resolve_scope(scope_id)
    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for entry in client.list_entries(scope):
        if entry.get("kind") != STATE_KIND:
            continue
        try:
            data = json.loads(entry.get("text") or "")
        except json.JSONDecodeError:
            continue
        if data.get("task_id") != task_id:
            continue
        candidates.append((str(data.get("saved_at") or ""), entry, data))
    if not candidates:
        return None, scope, None
    candidates.sort(key=lambda item: item[0])
    _, entry, data = candidates[-1]
    artifact = entry.get("artifact") or {}
    meta = {
        "artifact_id": artifact.get("artifact_id"),
        "revision": artifact.get("revision"),
        "state_version": entry.get("state_version"),
        "state": entry.get("state"),
    }
    return TaskState.from_dict(data), scope, meta


def list_task_states(
    client: PowerContextClient,
    *,
    scope_id: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    scope = client.resolve_scope(scope_id)
    states: list[dict[str, Any]] = []
    for entry in client.list_entries(scope, include_inactive=True):
        if entry.get("kind") != STATE_KIND:
            continue
        try:
            data = json.loads(entry.get("text") or "")
        except json.JSONDecodeError:
            continue
        artifact = entry.get("artifact") or {}
        states.append(
            {
                "task_id": data.get("task_id"),
                "phase": data.get("phase"),
                "saved_at": data.get("saved_at"),
                "context_hash": data.get("context_hash"),
                "artifact_id": artifact.get("artifact_id"),
                "revision": artifact.get("revision"),
                "state": entry.get("state"),
            }
        )
    states.sort(key=lambda item: str(item.get("saved_at") or ""))
    return states, scope
