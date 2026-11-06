from __future__ import annotations

import json
from typing import Iterator, Sequence

import httpx

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key.strip()
        self.model = settings.llm_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages: Sequence[dict[str, str]], stream: bool, **kwargs) -> dict:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "temperature": kwargs.get("temperature", 0.2),
            "max_tokens": kwargs.get("max_tokens", 2000),
        }
        return payload

    def chat(self, messages: Sequence[dict[str, str]], **kwargs) -> str:
        if not self.configured:
            raise RuntimeError("LLM is not configured. Set OPENAI_API_KEY in .env")
        with httpx.Client(timeout=180.0) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                json=self._payload(messages, stream=False, **kwargs),
                headers=self._headers(),
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"LLM API failed ({response.status_code}): {response.text[:500]}"
            )
        body = response.json()
        return body["choices"][0]["message"]["content"] or ""

    def stream(self, messages: Sequence[dict[str, str]], **kwargs) -> Iterator[str]:
        if not self.configured:
            raise RuntimeError("LLM is not configured. Set OPENAI_API_KEY in .env")
        payload = self._payload(messages, stream=True, **kwargs)
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"LLM API failed ({response.status_code}): {detail[:500]}"
                    )
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
