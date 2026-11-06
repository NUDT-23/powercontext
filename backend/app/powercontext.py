from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Settings
from .tracing import trace


class PowerContextError(RuntimeError):
    pass


class PowerContextClient:
    """Small typed facade over the PowerContext HTTP API with an auditable trace."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.powercontext_url.rstrip("/")
        self.timeout = settings.powercontext_timeout
        self.token = settings.powercontext_token.strip()
        self.data_dir = settings.data_dir

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, op: str, payload: dict | None = None) -> dict:
        started = time.perf_counter()
        status = None
        error = None
        body: Any = None
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self._headers(),
                )
            status = response.status_code
            if response.headers.get("content-type", "").startswith("application/json"):
                body = response.json()
            else:
                body = {"text": response.text[:1000]}
            if response.status_code >= 400:
                raise PowerContextError(
                    f"PowerContext {op} failed ({response.status_code}): {response.text[:500]}"
                )
            return body
        except Exception as exc:  # noqa: BLE001 - trace then re-raise
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            trace(
                "powercontext",
                {
                    "op": op,
                    "method": method,
                    "path": path,
                    "status": status,
                    "latency_ms": latency_ms,
                    "request": payload,
                    "response": body if isinstance(body, dict) else {"text": str(body)[:1000]},
                    "error": error,
                },
                data_dir=self.data_dir,
            )

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url}/health/live")
            return response.status_code < 400
        except Exception:  # noqa: BLE001
            return False

    def ensure_scope(self, project_id: str, title: str, summary: str = "") -> str:
        payload = {
            "title": title[:200],
            "summary": (summary or title)[:1000],
            "idempotency_key": f"paperlens-{project_id}",
        }
        try:
            body = self._request("POST", "/v1/scopes", "ensure_scope", payload)
            scope_id = body.get("scope_id") or (body.get("scope") or {}).get("scope_id")
            if scope_id:
                return str(scope_id)
            raise PowerContextError(f"Scope response has no scope_id: {body}")
        except PowerContextError:
            raise

    def remember(self, scope_id: str, text: str, kind: str = "preference", reason: str = "") -> dict:
        payload = {
            "scope_id": scope_id,
            "kind": kind,
            "text": text,
            "reason": reason or "saved by PaperLens",
        }
        return self._request("POST", "/v1/memory/remember", "remember", payload)

    def search_memory(self, scope_id: str, query: str, limit: int = 10) -> list[dict]:
        payload = {"scope_id": scope_id, "query": query, "mode": "text", "limit": limit}
        body = self._request("POST", "/v1/atomic-memory/search", "search_memory", payload)
        hits = body.get("hits") or body.get("results") or []
        memories: list[dict] = []
        for hit in hits:
            memory = hit.get("memory") or hit
            content = memory.get("content") or {}
            text = content.get("text") or memory.get("text") or hit.get("text") or ""
            if not text:
                continue
            memories.append(
                {
                    "text": text,
                    "kind": content.get("kind") or memory.get("kind") or "memory",
                    "artifact": memory.get("artifact") or content.get("artifact"),
                    "state_version": memory.get("state_version"),
                    "score": hit.get("score"),
                    "matched_by": hit.get("matched_by"),
                }
            )
        return memories

    def list_memory(self, scope_id: str, limit: int = 50) -> list[dict]:
        payload = {"scope_id": scope_id, "states": ["active"], "limit": limit}
        body = self._request("POST", "/v1/atomic-memory/list", "list_memory", payload)
        items = body.get("items") or []
        memories: list[dict] = []
        for item in items:
            content = item.get("content") or {}
            text = content.get("text") or item.get("text") or ""
            if not text:
                continue
            memories.append(
                {
                    "text": text,
                    "kind": content.get("kind") or item.get("kind") or "memory",
                    "artifact": item.get("artifact") or content.get("artifact"),
                    "state_version": item.get("state_version"),
                    "created_at": item.get("created_at"),
                }
            )
        return memories

    def prepare(self, scope_id: str, query: str, max_bytes: int = 4000) -> str:
        payload = {"scope_id": scope_id, "query": query, "max_bytes": max_bytes}
        body = self._request("POST", "/v1/context/prepare", "prepare_context", payload)
        return body.get("content") or ""

    def forget(self, scope_id: str, artifact: dict, state_version: int) -> dict:
        payload = {
            "scope_id": scope_id,
            "target": {"artifact": artifact, "state_version": state_version},
            "state": "forgotten",
        }
        return self._request("POST", "/v1/atomic-memory/lifecycle", "forget_memory", payload)

    def capture_source(self, scope_id: str, source_id: str, content: str, metadata: dict | None = None) -> dict:
        payload = {
            "scope_id": scope_id,
            "source_id": source_id,
            "content": content,
            "metadata": metadata or {},
        }
        return self._request("POST", "/v1/sources/content", "capture_source", payload)
