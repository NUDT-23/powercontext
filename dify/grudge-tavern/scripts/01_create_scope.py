#!/usr/bin/env python3
"""Create (idempotently) the PowerContext scope used by the tavern.

Outputs dify/.local/scope.json, which the later scripts read.

Usage:
    python scripts/01_create_scope.py
    python scripts/01_create_scope.py --seed     # add optional tavern lore
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client as pc  # noqa: E402

SCOPE_FILE_NAME = "scope.json"
IDEMPOTENCY_KEY = "grudge-tavern-v1"
SEED_MEMORIES = [
    (
        "vault-note",
        "酒馆账本：常客“老猫”去年冬天赊了 12 枚银币买热葡萄酒，至今未还；"
        "老板娘格罗姆每晚会擦一遍账本，边擦边骂。",
    ),
    (
        "tavern-lore",
        "酒馆传闻：地下室的门每年只在月圆之夜打开一次，老板娘格罗姆从不解释原因，"
        "吟游诗人莉拉为此写过三首歌。",
    ),
]


def find_scope(scope_id: str) -> dict | None:
    try:
        return pc.get(f"/v1/scopes/{scope_id}")
    except pc.HttpError as exc:
        if exc.status == 404:
            return None
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="also write two tavern-lore memories")
    args = parser.parse_args()

    dify_dir, local_dir = pc.load_paths()
    pc.load_env_file(dify_dir / ".env")
    pc.load_env_file(dify_dir / "compose" / ".env")

    ready = pc.wait_ready()
    server = {}
    try:
        server = pc.get("/v1/server-info")
    except Exception:  # optional endpoint; keep going
        pass
    print(f"PowerContext ready at {pc.pc_url()} (access_mode={ready.get('checks', {}).get('access_mode')})")

    scope_file = local_dir / SCOPE_FILE_NAME
    scope: dict | None = None
    if scope_file.is_file():
        saved = json.loads(scope_file.read_text(encoding="utf-8"))
        scope = find_scope(saved.get("scope_id", ""))
        if scope:
            print(f"Reusing existing scope {scope['scope_id']} from {scope_file}")
        else:
            print(f"Saved scope {saved.get('scope_id')} no longer exists; creating a new one.")

    if scope is None:
        scope = pc.post(
            "/v1/scopes",
            {
                "title": "记仇酒馆 · Grudge Tavern",
                "summary": "跨会话记录玩家欠账、恶作剧、承诺与关系的共享记忆分区。",
                "idempotency_key": IDEMPOTENCY_KEY,
            },
        )
        print(f"Created scope {scope['scope_id']}")

    pc.dump_json(
        scope_file,
        {
            "scope_id": scope["scope_id"],
            "title": scope.get("title"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pc_url": pc.pc_url(),
            "server_info": server,
        },
    )

    if args.seed:
        existing = pc.post("/v1/atomic-memory/list", {"scope_id": scope["scope_id"], "limit": 50})
        texts = {item.get("text") for item in existing.get("items", [])}
        for kind, text in SEED_MEMORIES:
            if text in texts:
                print(f"Seed already present ({kind})")
                continue
            result = pc.post(
                "/v1/memory/remember",
                {"scope_id": scope["scope_id"], "kind": kind, "text": text},
            )
            print(f"Seeded {kind}: changed={result.get('changed')}")

    print()
    print("Next steps:")
    print("  python scripts/02_render_dsl.py     # fill scope id into the DSL")
    print("  python scripts/03_bootstrap_dify.py # import + publish in Dify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
