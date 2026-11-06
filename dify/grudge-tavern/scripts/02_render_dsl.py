#!/usr/bin/env python3
"""Render the committed DSL template into a runnable DSL.

The committed template keeps placeholders so no private scope id or token is
published. This script substitutes:
    __PC_URL__      -> PC_URL_IN_DOCKER (default http://powercontext:8000)
    __PC_SCOPE_ID__ -> scope id from .local/scope.json (or PC_SCOPE_ID)
    __PC_TOKEN__    -> PC_TOKEN (may stay empty in disabled access mode)

Result: dify/.local/app.local.yaml, consumed by 03_bootstrap_dify.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client as pc  # noqa: E402

PLACEHOLDERS = ("__PC_URL__", "__PC_SCOPE_ID__", "__PC_TOKEN__")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", default="app/grudge-tavern.dsl.yaml")
    parser.add_argument("--output", default=".local/app.local.yaml")
    args = parser.parse_args()

    dify_dir, local_dir = pc.load_paths()
    pc.load_env_file(dify_dir / ".env")
    pc.load_env_file(dify_dir / "compose" / ".env")

    template = (dify_dir / args.template).resolve()
    if not template.is_file():
        pc.die(f"DSL template not found: {template}")

    scope_id = pc.env("PC_SCOPE_ID")
    scope_file = local_dir / "scope.json"
    if scope_file.is_file():
        scope_id = json.loads(scope_file.read_text(encoding="utf-8")).get("scope_id", scope_id)
    if not scope_id or scope_id == "scp_replace_me":
        pc.die("No scope id. Run scripts/01_create_scope.py first (or set PC_SCOPE_ID).")

    values = {
        "__PC_URL__": pc.env("PC_URL_IN_DOCKER", "http://powercontext:8000").rstrip("/"),
        "__PC_SCOPE_ID__": scope_id,
        "__PC_TOKEN__": pc.env("PC_TOKEN"),
    }

    text = template.read_text(encoding="utf-8")
    for marker, value in values.items():
        text = text.replace(f'"{marker}"', json.dumps(value))

    leftovers = [marker for marker in PLACEHOLDERS if marker in text]
    if leftovers:
        pc.die(f"Unreplaced placeholders: {', '.join(leftovers)}")

    output = (dify_dir / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {output}")
    print(f"  PC_URL     = {values['__PC_URL__']}")
    print(f"  PC_SCOPE_ID= {values['__PC_SCOPE_ID__']}")
    print(f"  PC_TOKEN   = {'set' if values['__PC_TOKEN__'] else '(empty, access mode disabled)'}")
    print()
    print("Next: python scripts/03_bootstrap_dify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
