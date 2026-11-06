from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path
from typing import Any

from .config import Settings
from .evidence import sha256_json, sha256_text, utc_now, write_json
from .ingestion import open_store
from .minimax_client import MiniMaxClient, extract_code_block, extract_json_object
from .models import ContextBundle
from .retrieval import build_bundle, default_task_id, summarize_bundle

SYSTEM_PROMPT = (
    "You are a senior Python engineer working in a spec-driven development workflow. "
    "You receive the task, the relevant specification sections, the current implementation, "
    "and the target tests. Implement the specification exactly and preserve existing behavior. "
    "Return one JSON object and nothing else, with exactly these keys: "
    '"analysis" (string), "changes" (array of strings), "updated_file" (string with the '
    'complete new file content), "confidence" (number between 0 and 1). '
    "Do not wrap updated_file in markdown fences."
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_code_fence(text: str) -> str:
    match = re.match(r"^\s*```(?:python)?\s*(.*?)\s*```\s*$", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text


def _unique_paths(items: list[Any], project_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for item in items:
        path = project_dir / item.path
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        paths.append(path)
    return paths


def build_messages(
    settings: Settings,
    task: str,
    bundle: ContextBundle,
    target_rel: str,
    base_text: str,
    feedback: str | None = None,
) -> list[dict[str, str]]:
    sections: list[str] = [f"TASK:\n{task.strip()}"]

    spec_paths = _unique_paths([*bundle.specs], settings.project_dir)
    if spec_paths:
        spec_blob = "\n\n".join(f"--- {path.name} ---\n{_read(path)}" for path in spec_paths)
        sections.append(f"SPECIFICATIONS:\n{spec_blob}")

    test_paths = _unique_paths([*bundle.tests], settings.project_dir)
    if test_paths:
        test_blob = "\n\n".join(f"--- {path.name} ---\n{_read(path)}" for path in test_paths)
        sections.append(f"TESTS (must pass after your change):\n{test_blob}")

    code_paths = _unique_paths([*bundle.code], settings.project_dir)
    other_code = [path for path in code_paths if path.name != Path(target_rel).name]
    if other_code:
        code_blob = "\n\n".join(f"--- {path.name} ---\n{_read(path)}" for path in other_code)
        sections.append(f"RELATED CODE:\n{code_blob}")

    sections.append(f"CURRENT FILE ({target_rel}):\n```python\n{base_text}\n```")
    if feedback:
        sections.append(
            "PREVIOUS ATTEMPT FAILED THESE TESTS (fix the implementation):\n"
            + feedback[-6000:]
        )
    sections.append(
        "Implement the task in CURRENT FILE. Keep imports valid, keep the module importable, "
        "and do not modify tests. Return the JSON object described in the system instructions."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(sections)},
    ]


def _unified_diff(base_text: str, updated_text: str, target_rel: str) -> str:
    base_lines = base_text.splitlines(keepends=True)
    updated_lines = updated_text.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            base_lines,
            updated_lines,
            fromfile=f"a/{target_rel}",
            tofile=f"b/{target_rel}",
        )
    )


def _dev_record(
    *,
    task: str,
    task_id: str,
    model: str,
    base_hash: str,
    updated_hash: str,
    patch_hash: str,
    analysis: str,
    changes: list[str],
    sources: list[str],
    diff: str,
) -> str:
    change_lines = "\n".join(f"- {change}" for change in changes) or "- (none reported)"
    source_lines = "\n".join(f"- {source}" for source in sources) or "- (none)"
    return f"""# MiniMax development record

- Task: {task}
- Task ID: `{task_id}`
- Model: `{model}`
- Generated at: {utc_now()}
- Base file SHA-256: `{base_hash}`
- Updated file SHA-256: `{updated_hash}`
- Patch SHA-256: `{patch_hash}`

## Context sources supplied to MiniMax

{source_lines}

## Model analysis

{analysis.strip() or "(empty)"}

## Reported changes

{change_lines}

## Unified diff

```diff
{diff.rstrip()}
```

The updated file SHA-256 above is the hash of the file produced from the model's
`updated_file` field. The patch SHA-256 is the hash of this diff, and the diff is the
exact delta between the base snapshot and the model output.
"""


def generate(
    settings: Settings,
    task: str,
    *,
    task_id: str | None = None,
    target_rel: str = "bookvault/search.py",
    base_path: Path | None = None,
    apply: bool = False,
    print_prompt: bool = False,
    limit: int = 6,
    feedback: str | None = None,
) -> dict[str, Any]:
    task_id = task_id or default_task_id(task)
    target = settings.project_dir / target_rel
    base_file = base_path or target
    base_text = _read(base_file)

    store = open_store(settings)
    bundle = build_bundle(store, task, task_id=task_id, limit=limit)
    messages = build_messages(settings, task, bundle, target_rel, base_text, feedback=feedback)

    if print_prompt:
        result = {
            "task": task,
            "task_id": task_id,
            "target": target_rel,
            "base": str(base_file),
            "base_sha256": sha256_text(base_text),
            "context": summarize_bundle(bundle),
            "messages": messages,
        }
        write_json(settings.artifacts_dir / "dev_record" / "prompt.json", result)
        return result

    if not settings.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY is not configured; copy .env.example to .env and fill it")

    client = MiniMaxClient(
        settings.minimax_api_key,
        settings.minimax_base_url,
        settings.minimax_model,
        settings.minimax_temperature,
    )
    completion = client.chat(messages)
    payload = extract_json_object(completion.text) or {}
    updated_text = str(payload.get("updated_file") or "")
    if not updated_text.strip():
        updated_text = extract_code_block(completion.text) or ""
    if not updated_text.strip():
        raise RuntimeError("MiniMax response did not contain updated_file content")
    updated_text = _strip_code_fence(updated_text)
    if not updated_text.endswith("\n"):
        updated_text += "\n"

    try:
        ast.parse(updated_text)
    except SyntaxError as exc:
        raise RuntimeError(f"MiniMax produced invalid Python: {exc}") from exc

    analysis = str(payload.get("analysis") or "")
    changes = [str(item) for item in payload.get("changes") or []]
    confidence = payload.get("confidence")

    diff = _unified_diff(base_text, updated_text, target_rel)
    base_hash = sha256_text(base_text)
    updated_hash = sha256_text(updated_text)
    patch_hash = sha256_text(diff)

    artifacts = settings.artifacts_dir
    dev_dir = artifacts / "dev_record"
    write_json(
        dev_dir / "minimax_request.json",
        {
            "generated_at": utc_now(),
            "model": completion.model,
            "temperature": settings.minimax_temperature,
            "messages": messages,
            "context_hash": bundle.context_hash,
            "sources": summarize_bundle(bundle)["sources"],
        },
    )
    write_json(
        dev_dir / "minimax_response.json",
        {
            "generated_at": utc_now(),
            "model": completion.model,
            "usage": completion.usage,
            "raw_text": completion.text,
            "parsed": payload,
        },
    )
    write_json(
        dev_dir / "minimax_meta.json",
        {
            "generated_at": utc_now(),
            "task": task,
            "task_id": task_id,
            "model": completion.model,
            "usage": completion.usage,
            "confidence": confidence,
            "base_sha256": base_hash,
            "updated_sha256": updated_hash,
            "patch_sha256": patch_hash,
        },
    )
    (artifacts / "changes.patch").write_text(diff, encoding="utf-8")
    (artifacts / "after").mkdir(parents=True, exist_ok=True)
    (artifacts / "after" / target.name).write_text(updated_text, encoding="utf-8")

    sources = [
        f"{item.kind}: {item.path} :: {item.symbol} (lines {item.line_start}-{item.line_end})"
        for item in [*bundle.specs, *bundle.code, *bundle.tests]
    ]
    record = _dev_record(
        task=task,
        task_id=task_id,
        model=completion.model,
        base_hash=base_hash,
        updated_hash=updated_hash,
        patch_hash=patch_hash,
        analysis=analysis,
        changes=changes,
        sources=sources,
        diff=diff,
    )
    (dev_dir / "dev_record.md").write_text(record, encoding="utf-8")

    if apply:
        target.write_text(updated_text, encoding="utf-8")

    return {
        "task": task,
        "task_id": task_id,
        "model": completion.model,
        "target": str(target),
        "base": str(base_file),
        "applied": apply,
        "base_sha256": base_hash,
        "updated_sha256": updated_hash,
        "patch_sha256": patch_hash,
        "analysis": analysis,
        "changes": changes,
        "confidence": confidence,
        "context_hash": bundle.context_hash,
        "diff": diff,
        "outputs": {
            "patch": str(artifacts / "changes.patch"),
            "after": str(artifacts / "after" / target.name),
            "dev_record": str(dev_dir / "dev_record.md"),
            "request": str(dev_dir / "minimax_request.json"),
            "response": str(dev_dir / "minimax_response.json"),
        },
    }
