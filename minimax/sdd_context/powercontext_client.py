from __future__ import annotations

from typing import Any

import httpx


class PowerContextClient:
    """Minimal PowerContext v1 client for scope selection and Atomic Memory."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PowerContextClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"PowerContext {method} {path} -> {response.status_code}: {response.text[:800]}"
            )
        return response.json()

    def live(self) -> bool:
        response = self._client.get("/health/live")
        return response.status_code == 200

    def server_info(self) -> dict[str, Any]:
        return self._request("GET", "/v1/server-info")

    def default_scope(self) -> dict[str, Any]:
        return self._request("GET", "/v1/scopes/default")

    def resolve_scope(self, scope_id: str | None = None) -> str:
        if scope_id:
            return scope_id
        return str(self.default_scope()["scope_id"])

    def remember(
        self,
        scope_id: str,
        kind: str,
        text: str,
        *,
        description: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_id": scope_id, "kind": kind, "text": text}
        if description:
            payload["description"] = description
        if reason:
            payload["reason"] = reason
        return self._request("POST", "/v1/memory/remember", json=payload)

    def list_entries(
        self,
        scope_id: str,
        *,
        limit: int = 100,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):
            payload: dict[str, Any] = {
                "scope_id": scope_id,
                "limit": max(1, min(limit, 100)),
                "include_inactive": include_inactive,
            }
            if cursor:
                payload["cursor"] = cursor
            result = self._request("POST", "/v1/memory/entries/list", json=payload)
            entries.extend(result.get("entries", []))
            cursor = result.get("next_cursor")
            if not cursor:
                break
        return entries

    def search(self, scope_id: str, query: str, *, limit: int = 10, mode: str = "auto") -> dict[str, Any]:
        payload = {"scope_id": scope_id, "query": query, "limit": limit, "mode": mode}
        return self._request("POST", "/v1/memory/search", json=payload)
