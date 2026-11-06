#!/usr/bin/env python3
"""Collect workflow run traces from the Dify console for the evidence folder.

Fetches the latest service-API runs of the tavern app, plus their node
executions, so judges can see the order:
    prepare_memory -> list_memories -> merge_memory -> narrate -> remember

Usage:
    python scripts/05_collect_trace.py [--runs 2] [--evidence-dir evidence]

Requires .local/dify.json (from 03) and the console credentials in dify/.env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client as pc  # noqa: E402
from dify_client import DifyClient, DifyError, login  # noqa: E402


def redact(payload: object, secrets: list[str]) -> object:
    text = json.dumps(payload, ensure_ascii=False)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--evidence-dir", default="evidence")
    args = parser.parse_args()

    dify_dir, local_dir = pc.load_paths()
    pc.load_env_file(dify_dir / ".env")
    pc.load_env_file(dify_dir / "compose" / ".env")

    state_file = local_dir / "dify.json"
    if not state_file.is_file():
        pc.die("Missing .local/dify.json; run scripts/03_bootstrap_dify.py first.")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    app_id = state.get("app_id")
    base_url = state.get("base_url") or pc.env("DIFY_BASE_URL", "http://127.0.0.1:8088")
    if not app_id:
        pc.die(".local/dify.json has no app_id.")

    email = pc.env("DIFY_CONSOLE_EMAIL")
    password = pc.env("DIFY_CONSOLE_PASSWORD")
    if not email or not password:
        pc.die("Set DIFY_CONSOLE_EMAIL and DIFY_CONSOLE_PASSWORD in dify/.env.")

    scope_id = ""
    scope_file = local_dir / "scope.json"
    if scope_file.is_file():
        scope_id = json.loads(scope_file.read_text(encoding="utf-8")).get("scope_id", "")
    secrets = [state.get("api_key", ""), scope_id]

    client = DifyClient(base_url)
    login(client, email, password)

    status, listing = client.request(
        "GET",
        f"/console/api/apps/{app_id}/advanced-chat/workflow-runs"
        f"?triggered_from=app-run&limit={max(args.runs, 1)}",
    )
    if status != 200:
        raise DifyError(f"workflow run list failed: HTTP {status} {listing}")

    runs = (listing.get("data") or [])[: args.runs]
    if not runs:
        pc.die(
            "No service-API workflow runs found. Run scripts/04_verify.py first "
            "(runs triggered from the Dify web UI are not included)."
        )

    evidence_dir = (dify_dir / args.evidence_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    for index, run in enumerate(runs, start=1):
        run_id = run["id"]
        status, detail = client.request(
            "GET", f"/console/api/apps/{app_id}/workflow-runs/{run_id}"
        )
        if status != 200:
            raise DifyError(f"workflow run {run_id} detail failed: HTTP {status} {detail}")
        status, nodes = client.request(
            "GET",
            f"/console/api/apps/{app_id}/workflow-runs/{run_id}/node-executions",
        )
        if status != 200:
            raise DifyError(
                f"workflow run {run_id} node executions failed: HTTP {status} {nodes}"
            )

        executions = nodes.get("data") or []
        detail_redacted = redact(detail, secrets)
        nodes_redacted = redact(executions, secrets)
        (evidence_dir / f"workflow-run-{index}.json").write_text(
            json.dumps(detail_redacted, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (evidence_dir / f"workflow-run-{index}.nodes.json").write_text(
            json.dumps(nodes_redacted, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        print(f"[trace] run {index}: {run_id} status={run.get('status')}")
        for node in executions:
            print(
                f"    {node.get('index', '?')}. "
                f"{node.get('title') or node.get('node_id')} "
                f"[{node.get('node_type')}] -> {node.get('status')}"
            )

    print(f"Evidence written to {evidence_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DifyError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
