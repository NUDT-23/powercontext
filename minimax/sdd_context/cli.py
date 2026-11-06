from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .evidence import utc_now, write_json
from .ingestion import ingest, open_store
from .models import TaskState
from .patchgen import generate
from .powercontext_client import PowerContextClient
from .retrieval import build_bundle, default_task_id, extract_keywords, summarize_bundle
from .state import list_task_states, load_task_state, save_task_state


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _settings() -> Settings:
    return Settings.load()


def _client(settings: Settings) -> PowerContextClient:
    return PowerContextClient(settings.powercontext_url)


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = _settings()
    _print(ingest(settings, record=not args.no_record))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    settings = _settings()
    task_id = args.task_id or default_task_id(args.task)
    state: TaskState | None = None
    state_meta: dict[str, Any] | None = None
    if args.attach_state:
        with _client(settings) as client:
            state, _, state_meta = load_task_state(client, task_id, scope_id=settings.scope_id)
        if state is None:
            print(f"no saved state for task {task_id}", file=sys.stderr)
            return 2

    store = open_store(settings)
    bundle = build_bundle(store, args.task, task_id=task_id, state=state, limit=args.limit)
    output = settings.artifacts_dir / "run" / "context.json"
    write_json(output, bundle.to_dict())
    summary = summarize_bundle(bundle)
    summary["keywords"] = extract_keywords(args.task)[:24]
    summary["output"] = str(output)
    if state_meta is not None:
        summary["state_meta"] = state_meta
    _print(summary)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings()
    task_id = args.task_id or default_task_id(args.task)
    ingestion = ingest(settings)
    store = open_store(settings)
    bundle = build_bundle(store, args.task, task_id=task_id, limit=args.limit)

    state = TaskState(
        task_id=task_id,
        task=args.task,
        phase="context_ready",
        completed=["ingest", "retrieve"],
        pending=["generate_patch", "apply_patch", "run_tests", "verify"],
        verification={
            "ingest": {
                "documents": ingestion["documents"],
                "by_kind": ingestion["by_kind"],
                "total_in_db": ingestion["stats"]["total"],
            }
        },
        context_hash=bundle.context_hash,
        saved_at=utc_now(),
    )
    bundle.state = state

    with _client(settings) as client:
        saved = save_task_state(client, state, scope_id=settings.scope_id)

    run_dir = settings.artifacts_dir / "run"
    write_json(run_dir / "context.json", bundle.to_dict())
    write_json(run_dir / "state.json", state.__dict__)
    write_json(run_dir / "powercontext_state.json", saved)

    summary = summarize_bundle(bundle)
    summary["ingest"] = {
        "documents": ingestion["documents"],
        "by_kind": ingestion["by_kind"],
        "stats": ingestion["stats"],
    }
    summary["state"] = state.__dict__
    summary["state_saved"] = saved
    summary["outputs"] = [
        str(run_dir / "context.json"),
        str(run_dir / "state.json"),
        str(run_dir / "powercontext_state.json"),
        str(run_dir / "ingest.json"),
    ]
    _print(summary)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    settings = _settings()
    with _client(settings) as client:
        state, scope, state_meta = load_task_state(client, args.task_id, scope_id=settings.scope_id)
    if state is None:
        print(f"no saved state for task {args.task_id}", file=sys.stderr)
        return 2

    task = args.task or state.task
    store = open_store(settings)
    bundle = build_bundle(store, task, task_id=state.task_id, state=state, limit=args.limit)
    result = {
        "resumed_at": utc_now(),
        "scope_id": scope,
        "state": state.__dict__,
        "state_record": state_meta,
        "context_hash_match": bundle.context_hash == state.context_hash,
        "saved_context_hash": state.context_hash,
        "current_context_hash": bundle.context_hash,
        "bundle": summarize_bundle(bundle),
    }
    output = settings.artifacts_dir / "run" / "resume.json"
    write_json(output, result)
    result["output"] = str(output)
    _print(result)
    return 0 if result["context_hash_match"] else 3


def cmd_state_save(args: argparse.Namespace) -> int:
    settings = _settings()
    state = TaskState(
        task_id=args.task_id,
        task=args.task,
        phase=args.phase,
        completed=list(args.completed or []),
        pending=list(args.pending or []),
        verification={},
        context_hash=args.context_hash or "",
        saved_at=utc_now(),
    )
    with _client(settings) as client:
        saved = save_task_state(client, state, scope_id=settings.scope_id)
    write_json(settings.artifacts_dir / "run" / "state.json", state.__dict__)
    _print({"state": state.__dict__, "saved": saved})
    return 0


def cmd_state_list(args: argparse.Namespace) -> int:
    settings = _settings()
    with _client(settings) as client:
        states, scope = list_task_states(client, scope_id=settings.scope_id)
    _print({"scope_id": scope, "states": states})
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    settings = _settings()
    result = generate(
        settings,
        args.task,
        task_id=args.task_id,
        target_rel=args.target,
        base_path=Path(args.base) if args.base else None,
        apply=args.apply,
        print_prompt=args.print_prompt,
        limit=args.limit,
    )
    if args.print_prompt:
        summary = {key: value for key, value in result.items() if key != "messages"}
        summary["message_count"] = len(result["messages"])
        summary["prompt_output"] = str(settings.artifacts_dir / "dev_record" / "prompt.json")
        _print(summary)
    else:
        summary = {key: value for key, value in result.items() if key != "diff"}
        summary["diff_lines"] = len(result["diff"].splitlines())
        _print(summary)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = _settings()
    _print(open_store(settings).stats())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdd-context",
        description="Spec-driven context module backed by embedded seekdb and PowerContext.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="ingest specs, code and tests into seekdb")
    ingest_parser.add_argument("--no-record", action="store_true", help="do not write artifacts/run/ingest.json")
    ingest_parser.set_defaults(func=cmd_ingest)

    context_parser = sub.add_parser("context", help="retrieve task context from seekdb")
    context_parser.add_argument("--task", required=True)
    context_parser.add_argument("--task-id")
    context_parser.add_argument("--limit", type=int, default=6)
    context_parser.add_argument("--attach-state", action="store_true", help="attach state saved in PowerContext")
    context_parser.set_defaults(func=cmd_context)

    run_parser = sub.add_parser("run", help="ingest, retrieve context and save task state")
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--task-id")
    run_parser.add_argument("--limit", type=int, default=6)
    run_parser.set_defaults(func=cmd_run)

    resume_parser = sub.add_parser("resume", help="reload saved state and rebuild context after restart")
    resume_parser.add_argument("--task-id", required=True)
    resume_parser.add_argument("--task")
    resume_parser.add_argument("--limit", type=int, default=6)
    resume_parser.set_defaults(func=cmd_resume)

    state_parser = sub.add_parser("state", help="inspect or write PowerContext task state")
    state_sub = state_parser.add_subparsers(dest="state_command", required=True)

    state_save = state_sub.add_parser("save", help="save a task checkpoint to PowerContext")
    state_save.add_argument("--task-id", required=True)
    state_save.add_argument("--task", required=True)
    state_save.add_argument("--phase", default="in_progress")
    state_save.add_argument("--completed", action="append", default=[])
    state_save.add_argument("--pending", action="append", default=[])
    state_save.add_argument("--context-hash", default="")
    state_save.set_defaults(func=cmd_state_save)

    state_list = state_sub.add_parser("list", help="list saved task checkpoints")
    state_list.set_defaults(func=cmd_state_list)

    generate_parser = sub.add_parser("generate", help="ask MiniMax to generate a spec-driven patch")
    generate_parser.add_argument("--task", required=True)
    generate_parser.add_argument("--task-id")
    generate_parser.add_argument("--target", default="bookvault/search.py")
    generate_parser.add_argument("--base", help="base snapshot to diff against (defaults to --target)")
    generate_parser.add_argument("--apply", action="store_true", help="write the model output into the project")
    generate_parser.add_argument("--print-prompt", action="store_true", help="write the prompt without calling MiniMax")
    generate_parser.add_argument("--limit", type=int, default=6)
    generate_parser.set_defaults(func=cmd_generate)

    stats_parser = sub.add_parser("stats", help="show seekdb collection statistics")
    stats_parser.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return int(args.func(args))
