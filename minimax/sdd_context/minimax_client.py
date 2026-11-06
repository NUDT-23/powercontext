from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class Completion:
    text: str
    model: str
    usage: dict[str, Any]


class MiniMaxClient:
    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.2) -> None:
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages: list[dict[str, str]], temperature: float | None = None) -> Completion:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        if not text:
            extra = getattr(choice.message, "model_extra", None) or {}
            text = str(extra.get("reasoning_content") or "")
        usage = response.usage.model_dump() if response.usage is not None else {}
        return Completion(text=text, model=response.model or self.model, usage=usage)


def extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(stripped[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def extract_code_block(text: str) -> str | None:
    match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    body = match.group(1).strip()
    return body or None
