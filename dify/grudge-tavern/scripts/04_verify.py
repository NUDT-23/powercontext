#!/usr/bin/env python3
"""Run the cross-session memory verification and collect evidence.

Two independent Dify conversations (different conversation ids, same service
API user) exercise the Grudge Tavern:

    session 1: the player runs a tab and breaks the bard's lute string
    session 2: a brand new chat asks whether the tavern remembers it

The script asserts that session 2's answer recalls session 1's facts, and
saves redacted request/response/practice evidence under grudge-tavern/evidence/.

Requires:
    .local/scope.json  (scripts/01_create_scope.py)
    .local/dify.json   (scripts/03_bootstrap_dify.py)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client as pc  # noqa: E402

QUERY_ONE = (
    "我是头一回来。先赊一壶你们最贵的招牌酒，记十二个银币在我账上。"
    "还有，我刚才手滑把莉拉的琴弦弄断了一根，你可别说是我干的。"
)
QUERY_TWO = "还认得我吗？说说看，我上次欠了多少银币，又弄坏了谁的琴弦？"
RECALL_MARKERS = ("12", "十二", "琴", "莉拉")


def service_chat(base_url: str, api_key: str, query: str,
                 conversation_id: str, user: str, timeout: int = 180) -> dict:
    url = base_url.rstrip("/") + "/v1/chat-messages"
    body = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": user,
        "files": [],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"chat-messages HTTP {exc.code}: {detail[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach Dify at {base_url}: {exc.reason}"
        ) from exc


def list_memories(scope_id: str, limit: int = 50) -> list[dict]:
    payload = pc.post(
        "/v1/atomic-memory/list", {"scope_id": scope_id, "limit": limit}
    )
    return payload.get("items", [])


def memory_texts(items: list[dict]) -> list[str]:
    return [item.get("text", "") for item in items]


def wait_for_memory(scope_id: str, needle: str, timeout: int = 20) -> list[dict]:
    deadline = time.time() + timeout
    items: list[dict] = []
    while time.time() < deadline:
        items = list_memories(scope_id)
        if any(needle in text for text in memory_texts(items)):
            return items
        time.sleep(2)
    return items


def prepare(scope_id: str, query: str) -> dict:
    return pc.post(
        "/v1/context/prepare",
        {
            "scope_id": scope_id,
            "query": "酒馆 玩家 格罗姆 莉拉 老K " + query[:600],
        },
        timeout=60,
    )


def redact(payload: object, api_key: str, scope_id: str) -> object:
    text = json.dumps(payload, ensure_ascii=False)
    text = text.replace(api_key, "app-***REDACTED***")
    text = text.replace(scope_id, "scp-***PUBLIC-DEMO***")
    return json.loads(text)


def save(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default="evidence")
    parser.add_argument("--query-one", default=QUERY_ONE)
    parser.add_argument("--query-two", default=QUERY_TWO)
    parser.add_argument("--user", default="verify-player")
    args = parser.parse_args()

    dify_dir, local_dir = pc.load_paths()
    pc.load_env_file(dify_dir / ".env")
    pc.load_env_file(dify_dir / "compose" / ".env")

    scope_file = local_dir / "scope.json"
    dify_file = local_dir / "dify.json"
    if not scope_file.is_file() or not dify_file.is_file():
        pc.die("Missing .local/scope.json or .local/dify.json; run scripts 01-03 first.")

    scope = json.loads(scope_file.read_text(encoding="utf-8"))
    app = json.loads(dify_file.read_text(encoding="utf-8"))
    scope_id = scope["scope_id"]
    api_key = app.get("api_key") or ""
    base_url = app.get("base_url") or pc.env("DIFY_BASE_URL", "http://127.0.0.1:8088")
    if not api_key:
        pc.die("No app API key in .local/dify.json; re-run 03_bootstrap_dify.py.")

    evidence_dir = (dify_dir / args.evidence_dir).resolve()
    started = datetime.now(timezone.utc).isoformat()

    print("[verify] PowerContext ready check")
    pc.wait_ready()

    before_items = list_memories(scope_id)
    print(f"[verify] memories before session 1: {len(before_items)}")

    print("[verify] session 1: running a tab and breaking the lute")
    t0 = time.time()
    response1 = service_chat(base_url, api_key, args.query_one, "", args.user)
    elapsed1 = round(time.time() - t0, 2)
    answer1 = response1.get("answer", "")
    if not answer1.strip():
        raise RuntimeError(f"session 1 returned an empty answer: {response1}")
    conversation1 = response1.get("conversation_id", "")
    print(f"[verify] session 1 ok in {elapsed1}s (conversation {conversation1})")

    items_after = wait_for_memory(scope_id, "酒馆记忆")
    new_items = [
        item for item in items_after
        if item.get("text") not in memory_texts(before_items)
    ]
    if not new_items:
        raise RuntimeError(
            "No new memory appeared in PowerContext after session 1. "
            "Check the workflow run for the remember node."
        )
    print(f"[verify] PowerContext gained {len(new_items)} memory item(s)")

    prepare_two = prepare(scope_id, args.query_two)
    prepared = prepare_two.get("root") or prepare_two
    if prepared.get("status") != "ready" or not prepared.get("content"):
        print("[verify] WARNING: prepare_context returned empty; the list fallback will carry recall")

    print("[verify] session 2: brand new conversation asks for recall")
    t0 = time.time()
    response2 = service_chat(base_url, api_key, args.query_two, "", args.user)
    elapsed2 = round(time.time() - t0, 2)
    answer2 = response2.get("answer", "")
    conversation2 = response2.get("conversation_id", "")
    if not answer2.strip():
        raise RuntimeError(f"session 2 returned an empty answer: {response2}")
    if conversation1 and conversation2 == conversation1:
        raise RuntimeError("session 2 reused session 1's conversation id; not cross-session")
    print(f"[verify] session 2 ok in {elapsed2}s (conversation {conversation2})")

    matched = [marker for marker in RECALL_MARKERS if marker in answer2]
    print(f"[verify] recall markers present in session 2: {matched}")

    save(evidence_dir / "session1.request.json", redact({
        "endpoint": "/v1/chat-messages",
        "conversation_id": "",
        "query": args.query_one,
        "user": args.user,
    }, api_key, scope_id))
    save(evidence_dir / "session1.response.json", redact({
        "conversation_id": conversation1,
        "answer": answer1,
        "elapsed_seconds": elapsed1,
        "metadata": response1.get("metadata", {}),
    }, api_key, scope_id))
    save(evidence_dir / "session2.request.json", redact({
        "endpoint": "/v1/chat-messages",
        "conversation_id": "",
        "query": args.query_two,
        "user": args.user,
    }, api_key, scope_id))
    save(evidence_dir / "session2.response.json", redact({
        "conversation_id": conversation2,
        "answer": answer2,
        "elapsed_seconds": elapsed2,
        "recall_markers": matched,
        "metadata": response2.get("metadata", {}),
    }, api_key, scope_id))
    save(evidence_dir / "powercontext.memory-list.json", redact({
        "before_session1_count": len(before_items),
        "after_session1_count": len(items_after),
        "new_items": new_items,
    }, api_key, scope_id))
    save(evidence_dir / "powercontext.prepare-session2.json", redact(
        prepare_two, api_key, scope_id
    ))
    save(evidence_dir / "verify.summary.json", {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "scope_id_redacted": True,
        "session1_conversation_id": conversation1,
        "session2_conversation_id": conversation2,
        "memories_before": len(before_items),
        "memories_after": len(items_after),
        "new_memories": len(new_items),
        "recall_markers": matched,
        "passed": len(matched) >= 2,
    })

    if len(matched) < 2:
        print()
        print("FAILED: session 2 did not recall enough facts from session 1.")
        print(f"answer 2:\n{answer2}")
        return 1

    print()
    print("PASSED: cross-session recall verified.")
    print(f"Evidence written to {evidence_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
