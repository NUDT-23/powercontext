from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Settings
from .evidence import sha256_file, sha256_text, utc_now, write_json
from .ingestion import ingest, open_store
from .models import TaskState
from .patchgen import _unified_diff, generate
from .powercontext_client import PowerContextClient
from .retrieval import build_bundle, default_task_id
from .state import list_task_states, load_task_state, save_task_state

TASK = "Implement tag filtering and limit validation in search_books per R2-R5"
TARGET_REL = "bookvault/search.py"
SPEC_REL = "specs/search-requirements.md"


class VerifyFailure(RuntimeError):
    pass


def _run_pytest(project_dir: Path, args: list[str], log_path: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "-rf", *args]
    process = subprocess.run(
        command,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = process.stdout + process.stderr
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    functional = bool(re.search(r"\bAssertionError\b", output))
    environment_error = bool(
        re.search(r"\b(ImportError|ModuleNotFoundError|SyntaxError|FileNotFoundError)\b", output)
    )
    return {
        "command": command,
        "cwd": str(project_dir),
        "exit_code": process.returncode,
        "passed": process.returncode == 0,
        "failed_nodeids": failed,
        "functional_failure": functional,
        "environment_error": environment_error,
        "log": str(log_path),
        "tail": output.splitlines()[-40:],
    }


def _filesystem_type(path: Path) -> str | None:
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    target = str(path.resolve())
    best: tuple[str, str] | None = None
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount = parts[1].replace("\\040", " ")
        if target == mount or target.startswith(mount.rstrip("/") + "/"):
            if best is None or len(mount) > len(best[0]):
                best = (mount, parts[2])
    return best[1] if best else None


_UNSUPPORTED_FILESYSTEMS = {
    "9p",
    "cifs",
    "drvfs",
    "fuseblk",
    "nfs",
    "nfs4",
    "smb3",
    "sshfs",
    "v9fs",
}


def _supports_fallocate(directory: Path) -> bool:
    if not hasattr(os, "posix_fallocate"):
        return False
    fstype = _filesystem_type(directory)
    if fstype and fstype.lower() in _UNSUPPORTED_FILESYSTEMS:
        return False
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".fallocate_probe"
    try:
        handle = os.open(probe, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
        try:
            os.posix_fallocate(handle, 0, 4096)
        finally:
            os.close(handle)
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _choose_db_path(artifacts_dir: Path) -> tuple[Path, str]:
    preferred = artifacts_dir / "run" / "verify" / "seekdb"
    if _supports_fallocate(preferred):
        shutil.rmtree(preferred, ignore_errors=True)
        return preferred, "artifacts/run/verify/seekdb"
    fallback = Path(tempfile.gettempdir()) / f"sdd_verify_seekdb_{uuid.uuid4().hex[:8]}"
    shutil.rmtree(fallback, ignore_errors=True)
    return fallback, "system_tempdir"


def _test_hashes(project_dir: Path) -> dict[str, str]:
    tests_dir = project_dir / "tests"
    return {
        path.relative_to(project_dir).as_posix(): sha256_file(path)
        for path in sorted(tests_dir.glob("*.py"))
    }


def _spec_hashes(project_dir: Path) -> dict[str, str]:
    specs_dir = project_dir / "specs"
    return {
        path.relative_to(project_dir).as_posix(): sha256_file(path)
        for path in sorted(specs_dir.glob("*.md"))
    }


def _write_test_hash_evidence(
    output: Path,
    before: dict[str, str],
    after: dict[str, str],
    specs_before: dict[str, str],
    specs_after: dict[str, str],
) -> None:
    lines = ["# SHA-256 evidence", ""]
    lines.append("## Test files (before / after MiniMax change)")
    for name in sorted(set(before) | set(after)):
        lines.append(f"{name}")
        lines.append(f"  before: {before.get(name, 'MISSING')}")
        lines.append(f"  after:  {after.get(name, 'MISSING')}")
        lines.append(f"  unchanged: {before.get(name) == after.get(name)}")
    lines.append("")
    lines.append("## Spec files (before / after re-ingest experiment)")
    for name in sorted(set(specs_before) | set(specs_after)):
        lines.append(f"{name}")
        lines.append(f"  before: {specs_before.get(name, 'MISSING')}")
        lines.append(f"  after:  {specs_after.get(name, 'MISSING')}")
        lines.append(f"  restored: {specs_before.get(name) == specs_after.get(name)}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _spec_update_check(settings: Settings) -> dict[str, Any]:
    spec_path = settings.project_dir / SPEC_REL
    original = spec_path.read_text(encoding="utf-8")
    marker = f"SDD_REINGEST_{uuid.uuid4().hex[:10].upper()}"
    updated = (
        original.rstrip()
        + f"\n\n## R7 re-ingest evidence {marker}\n\n"
        + f"Marker `{marker}` must become retrievable after re-ingestion and disappear after restore.\n"
    )
    try:
        spec_path.write_text(updated, encoding="utf-8")
        ingest(settings, record=False)
        store = open_store(settings)
        updated_rows = [
            row
            for row in store.all_rows()
            if marker in str(row.get("document") or "")
        ]
        updated_ids = [row["id"] for row in updated_rows]
        expected_id = f"spec:{SPEC_REL}:R7"
        found_after_update = expected_id in updated_ids
    finally:
        spec_path.write_text(original, encoding="utf-8")

    ingest(settings, record=False)
    store = open_store(settings)
    updated_rows_restored = [
        row for row in store.all_rows() if marker in str(row.get("document") or "")
    ]
    return {
        "spec": SPEC_REL,
        "marker": marker,
        "expected_chunk_id": f"spec:{SPEC_REL}:R7",
        "found_after_update": found_after_update,
        "updated_chunk_ids": updated_ids,
        "found_after_restore": bool(updated_rows_restored),
        "pass": found_after_update and not updated_rows_restored,
    }


def _state_check(
    settings: Settings,
    client: PowerContextClient,
    task_id: str,
    context_hash: str,
    db_path: Path,
) -> dict[str, Any]:
    states_before, scope = list_task_states(client, scope_id=settings.scope_id)
    existed_before = any(item.get("task_id") == task_id for item in states_before)

    state = TaskState(
        task_id=task_id,
        task=TASK,
        phase="context_ready",
        completed=["ingest", "retrieve"],
        pending=["generate_patch", "apply_patch", "run_tests"],
        verification={"context_hash": context_hash},
        context_hash=context_hash,
        saved_at=utc_now(),
    )
    saved = save_task_state(client, state, scope_id=scope)

    loaded, loaded_scope, meta = load_task_state(client, task_id, scope_id=scope)

    environment = os.environ.copy()
    environment["SDD_DB_PATH"] = str(db_path)
    resume = subprocess.run(
        [
            sys.executable,
            "-m",
            "sdd_context",
            "resume",
            "--task-id",
            task_id,
            "--task",
            TASK,
        ],
        cwd=str(settings.package_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    resume_output: dict[str, Any] = {}
    try:
        resume_output = json.loads(resume.stdout)
    except json.JSONDecodeError:
        resume_output = {}

    passed = (
        not existed_before
        and loaded is not None
        and loaded.task_id == task_id
        and loaded.context_hash == context_hash
        and resume.returncode == 0
        and bool(resume_output.get("context_hash_match"))
    )
    return {
        "scope_id": scope,
        "task_id": task_id,
        "state_absent_before_save": not existed_before,
        "saved": saved,
        "loaded": loaded.__dict__ if loaded else None,
        "loaded_record": meta,
        "resume_exit_code": resume.returncode,
        "resume_context_hash_match": resume_output.get("context_hash_match"),
        "resume_context_hash": resume_output.get("current_context_hash"),
        "resume_log_tail": resume.stdout.splitlines()[-10:] if resume.stdout else [],
        "pass": passed,
    }


def _verify_patch_consistency(
    after_path: Path,
    patch_path: Path,
    base_text: str,
    meta_path: Path,
    applied_path: Path,
) -> dict[str, Any]:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    updated_text = after_path.read_text(encoding="utf-8")
    patch_text = patch_path.read_text(encoding="utf-8")
    regenerated = _unified_diff(base_text, updated_text, TARGET_REL)
    checks = {
        "updated_hash_matches_meta": sha256_text(updated_text) == meta.get("updated_sha256"),
        "patch_hash_matches_meta": sha256_text(patch_text) == meta.get("patch_sha256"),
        "patch_equals_before_after_diff": patch_text == regenerated,
        "applied_file_matches_model_output": sha256_file(applied_path) == sha256_text(updated_text),
    }
    return {"meta": meta, "checks": checks, "pass": all(checks.values())}


def _render_sample(verification: dict[str, Any], path: Path) -> None:
    criteria = verification.get("criteria", {})

    def status(name: str) -> str:
        data = criteria.get(name) or {}
        if data.get("skipped"):
            return "SKIPPED"
        return "PASS" if data.get("pass") else "FAIL"

    before = criteria.get("tests_before") or {}
    after = criteria.get("tests_after") or {}
    context = criteria.get("context_retrieval") or {}
    spec_update = criteria.get("spec_update_reingest") or {}
    state = criteria.get("state_reuse") or {}
    minimax = criteria.get("minimax_participation") or {}
    ingest = criteria.get("seekdb_ingest_before") or {}

    lines = [
        "# 验收输出样例",
        "",
        f"- 生成时间：{verification.get('generated_at')}",
        f"- 结论：**{'PASS' if verification.get('overall_pass') else 'FAIL'}**",
        f"- 任务：`{verification.get('task_id')}`",
        f"- Python：{verification.get('environment', {}).get('python', '').splitlines()[0]}",
        f"- 数据库：`{verification.get('environment', {}).get('db_path')}`",
        "",
        "## 验收项",
        "",
        "| 验收项 | 结果 |",
        "| --- | --- |",
        f"| seekdb 入库 | {status('seekdb_ingest_before')} |",
        f"| 改动前测试 | {status('tests_before')} |",
        f"| 上下文检索 | {status('context_retrieval')} |",
        f"| 规格更新/重新入库 | {status('spec_update_reingest')} |",
        f"| PowerContext 状态复用 | {status('state_reuse')} |",
        f"| MiniMax 参与 | {status('minimax_participation')} |",
        f"| 改动后测试 | {status('tests_after')} |",
        "",
        "## seekdb",
        "",
        f"- 入库文档：{ingest.get('documents', 'n/a')}（{ingest.get('by_kind', {})}）",
        f"- 集合总数：{ingest.get('stats', {}).get('total', 'n/a')}",
        f"- 上下文来源数：{context.get('source_count', 'n/a')}；数据库查询次数：{context.get('db_query_count', 'n/a')}",
        "",
        "## 测试信号",
        "",
        f"- 改动前目标测试失败节点：{before.get('target', {}).get('failed_nodeids', [])}",
        f"- 改动前目标失败是否为功能断言：{before.get('target', {}).get('functional_failure')}",
        f"- 改动前回归测试：exit={before.get('regression', {}).get('exit_code')}",
        f"- 改动后目标测试：exit={after.get('target', {}).get('exit_code')}",
        f"- 改动后回归测试：exit={after.get('regression', {}).get('exit_code')}",
        f"- 测试文件哈希未变：{after.get('test_set_unchanged')}",
        "",
        "## 规格更新与重新入库",
        "",
        f"- 临时规格块：`{spec_update.get('expected_chunk_id')}`",
        f"- 更新后可检索：{spec_update.get('found_after_update')}",
        f"- 恢复后已清理：{not spec_update.get('found_after_restore')}",
        "",
        "## PowerContext 状态复用",
        "",
        f"- 保存前该任务无状态：{state.get('state_absent_before_save')}",
        f"- 新进程 resume 退出码：{state.get('resume_exit_code')}",
        f"- 恢复后上下文哈希一致：{state.get('resume_context_hash_match')}",
        f"- 状态 Artifact：`{(state.get('loaded_record') or {}).get('artifact_id')}`",
        "",
        "## MiniMax",
        "",
    ]
    if minimax.get("skipped"):
        lines.append("- 本次运行使用 `--skip-minimax`，未调用 MiniMax。")
    elif minimax.get("error"):
        lines.append(f"- 错误：{minimax.get('error')}")
    else:
        lines.extend(
            [
                f"- 模型：`{minimax.get('model')}`",
                f"- 置信度：{minimax.get('confidence')}",
                f"- 更新文件 SHA-256：`{minimax.get('updated_sha256')}`",
                f"- Patch SHA-256：`{minimax.get('patch_sha256')}`",
                f"- 一致性检查：{minimax.get('consistency', {}).get('checks', {})}",
                f"- 模型分析：{minimax.get('analysis', '')[:500]}",
            ]
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_verify(args: argparse.Namespace) -> int:
    package_root = Path(__file__).resolve().parents[1]
    settings = Settings.load()
    task_id = f"verify-{uuid.uuid4().hex[:8]}"

    run_dir = settings.artifacts_dir / "run"
    verify_dir = run_dir / "verify"
    db_path, db_selection = _choose_db_path(settings.artifacts_dir)
    settings = replace(settings, db_path=db_path, artifacts_dir=settings.artifacts_dir)
    project_dir = settings.project_dir

    target = project_dir / TARGET_REL
    before_snapshot = settings.artifacts_dir / "before" / "search.py"
    known_good_after = settings.artifacts_dir / "after" / "search.py"
    if not before_snapshot.exists():
        print(f"missing before snapshot: {before_snapshot}", file=sys.stderr)
        return 2

    original_target = target.read_text(encoding="utf-8")
    # generate() overwrites artifacts/after/search.py on every attempt, so snapshot the
    # last known-good file now to avoid restoring a failed model output.
    known_good_after_text = (
        known_good_after.read_text(encoding="utf-8") if known_good_after.exists() else None
    )
    final_ok = False
    keep_model_output = False

    verification: dict[str, Any] = {
        "generated_at": utc_now(),
        "task": TASK,
        "task_id": task_id,
        "environment": {
            "python": sys.version,
            "platform": sys.platform,
            "package_root": str(package_root),
            "project_dir": str(project_dir),
            "db_path": str(db_path),
            "db_selection": db_selection,
            "powercontext_url": settings.powercontext_url,
        },
        "criteria": {},
    }

    try:
        target.write_text(before_snapshot.read_text(encoding="utf-8"), encoding="utf-8")
        tests_before = _test_hashes(project_dir)
        specs_before = _spec_hashes(project_dir)

        ingestion_before = ingest(settings)
        verification["criteria"]["seekdb_ingest_before"] = {
            "documents": ingestion_before["documents"],
            "by_kind": ingestion_before["by_kind"],
            "stats": ingestion_before["stats"],
            "pass": ingestion_before["documents"] > 0
            and ingestion_before["stats"]["total"] == ingestion_before["documents"],
        }

        before_target = _run_pytest(
            project_dir,
            ["tests/test_search_target.py"],
            verify_dir / "tests_before_target.log",
        )
        before_regression = _run_pytest(
            project_dir,
            ["tests/test_search_regression.py"],
            verify_dir / "tests_before_regression.log",
        )
        verification["criteria"]["tests_before"] = {
            "target": before_target,
            "regression": before_regression,
            "pass": (
                not before_target["passed"]
                and bool(before_target["failed_nodeids"])
                and before_target["functional_failure"]
                and not before_target["environment_error"]
                and before_regression["passed"]
            ),
        }

        store = open_store(settings)
        bundle_before = build_bundle(store, TASK, task_id=task_id, limit=6)
        sources = [
            {
                "kind": item.kind,
                "path": item.path,
                "symbol": item.symbol,
                "lines": [item.line_start, item.line_end],
                "reasons": item.reasons,
                "excerpt": item.excerpt,
            }
            for item in [*bundle_before.specs, *bundle_before.code, *bundle_before.tests]
        ]
        missing_paths = [
            item.path
            for item in [*bundle_before.specs, *bundle_before.code, *bundle_before.tests]
            if not (project_dir / item.path).is_file()
        ]
        spec_hit = any(item.kind == "spec" for item in bundle_before.specs)
        code_hit = any(item.path == TARGET_REL for item in bundle_before.code)
        test_hit = any(item.kind == "test" for item in bundle_before.tests)
        write_json(verify_dir / "context_before.json", {
            "context_hash": bundle_before.context_hash,
            "sources": sources,
            "db_queries": bundle_before.db_queries,
        })
        verification["criteria"]["context_retrieval"] = {
            "context_hash": bundle_before.context_hash,
            "source_count": len(sources),
            "spec_hit": spec_hit,
            "target_code_hit": code_hit,
            "test_hit": test_hit,
            "missing_paths": missing_paths,
            "db_query_count": len(bundle_before.db_queries),
            "db_query_log": bundle_before.db_queries[:20],
            "pass": bool(sources) and spec_hit and code_hit and test_hit and not missing_paths,
        }

        spec_update = _spec_update_check(settings)
        verification["criteria"]["spec_update_reingest"] = spec_update

        try:
            with PowerContextClient(settings.powercontext_url) as client:
                state_result = _state_check(
                    settings,
                    client,
                    task_id,
                    bundle_before.context_hash,
                    db_path,
                )
        except Exception as exc:  # PowerContext unavailable is a hard failure for this criterion.
            state_result = {
                "error": str(exc),
                "hint": "start PowerContext and set POWERCONTEXT_URL",
                "pass": False,
            }
        verification["criteria"]["state_reuse"] = state_result

        if args.skip_minimax:
            minimax_result: dict[str, Any] = {"skipped": True, "pass": False}
            after_target: dict[str, Any] = {"skipped": True}
            after_regression: dict[str, Any] = {"skipped": True}
        else:
            if not settings.minimax_api_key:
                raise VerifyFailure(
                    "MINIMAX_API_KEY is not configured. Copy .env.example to .env and fill it, "
                    "or rerun with --skip-minimax to verify only the context/state pipeline."
                )
            feedback: str | None = None
            generation: dict[str, Any] = {}
            consistency: dict[str, Any] = {"pass": False}
            attempt_records: list[dict[str, Any]] = []
            after_target: dict[str, Any] = {"passed": False}
            after_regression: dict[str, Any] = {"passed": False}
            dev_dir = settings.artifacts_dir / "dev_record"
            for attempt in range(1, max(1, args.max_attempts) + 1):
                generation = generate(
                    settings,
                    TASK,
                    task_id=task_id,
                    target_rel=TARGET_REL,
                    base_path=before_snapshot,
                    apply=True,
                    limit=6,
                    feedback=feedback,
                )
                after_target = _run_pytest(
                    project_dir,
                    ["tests/test_search_target.py"],
                    verify_dir / f"tests_after_target_attempt{attempt}.log",
                )
                after_regression = _run_pytest(
                    project_dir,
                    ["tests/test_search_regression.py"],
                    verify_dir / f"tests_after_regression_attempt{attempt}.log",
                )
                consistency = _verify_patch_consistency(
                    settings.artifacts_dir / "after" / "search.py",
                    settings.artifacts_dir / "changes.patch",
                    before_snapshot.read_text(encoding="utf-8"),
                    dev_dir / "minimax_meta.json",
                    target,
                )
                attempt_dir = dev_dir / "attempts" / f"attempt-{attempt}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                for name in (
                    "minimax_request.json",
                    "minimax_response.json",
                    "minimax_meta.json",
                    "dev_record.md",
                ):
                    if (dev_dir / name).exists():
                        shutil.copy2(dev_dir / name, attempt_dir / name)
                attempt_records.append(
                    {
                        "attempt": attempt,
                        "model": generation.get("model"),
                        "updated_sha256": generation.get("updated_sha256"),
                        "patch_sha256": generation.get("patch_sha256"),
                        "target_tests_passed": after_target["passed"],
                        "regression_tests_passed": after_regression["passed"],
                        "consistency": consistency["pass"],
                    }
                )
                if after_target["passed"] and after_regression["passed"] and consistency["pass"]:
                    break
                feedback = (
                    f"Target tests exit={after_target['exit_code']}:\n"
                    + "\n".join(after_target["tail"])
                    + f"\nRegression tests exit={after_regression['exit_code']}:\n"
                    + "\n".join(after_regression["tail"])
                )

            keep_model_output = bool(
                after_target["passed"] and after_regression["passed"] and consistency["pass"]
            )
            minimax_result = {
                "skipped": False,
                "model": generation.get("model"),
                "context_hash": generation.get("context_hash"),
                "analysis": generation.get("analysis"),
                "changes": generation.get("changes"),
                "confidence": generation.get("confidence"),
                "base_sha256": generation.get("base_sha256"),
                "updated_sha256": generation.get("updated_sha256"),
                "patch_sha256": generation.get("patch_sha256"),
                "outputs": generation.get("outputs"),
                "consistency": consistency,
                "attempts": attempt_records,
                "pass": keep_model_output,
            }

        tests_after = _test_hashes(project_dir)
        specs_after = _spec_hashes(project_dir)
        _write_test_hash_evidence(
            settings.artifacts_dir / "test_and_spec_hashes.txt",
            tests_before,
            tests_after,
            specs_before,
            specs_after,
        )
        tests_unchanged = tests_before == tests_after
        verification["criteria"]["tests_after"] = {
            "target": after_target,
            "regression": after_regression,
            "test_set_unchanged": tests_unchanged,
            "tests_before_hashes": tests_before,
            "tests_after_hashes": tests_after,
            "pass": (
                not args.skip_minimax
                and bool(after_target.get("passed"))
                and bool(after_regression.get("passed"))
                and tests_unchanged
            ),
        }
        verification["criteria"]["minimax_participation"] = minimax_result

        final_ok = bool(
            verification["criteria"]["seekdb_ingest_before"]["pass"]
            and verification["criteria"]["tests_before"]["pass"]
            and verification["criteria"]["context_retrieval"]["pass"]
            and verification["criteria"]["spec_update_reingest"]["pass"]
            and verification["criteria"]["state_reuse"].get("pass")
            and verification["criteria"]["tests_after"]["pass"]
            and verification["criteria"]["minimax_participation"].get("pass")
        )
    except Exception as exc:
        verification["error"] = str(exc)
        final_ok = False
    finally:
        if not keep_model_output:
            restore_text = known_good_after_text if known_good_after_text is not None else original_target
            target.write_text(restore_text, encoding="utf-8")
        try:
            final_ingestion = ingest(settings)
            verification["final_ingest"] = {
                "documents": final_ingestion["documents"],
                "by_kind": final_ingestion["by_kind"],
                "stats": final_ingestion["stats"],
            }
        except Exception as exc:
            verification["final_ingest"] = {"error": str(exc)}
        verification["overall_pass"] = final_ok
        verification["finished_at"] = utc_now()
        write_json(settings.artifacts_dir / "run" / "verification.json", verification)
        _render_sample(verification, package_root / "docs" / "verification-sample.md")
        if db_selection == "system_tempdir":
            shutil.rmtree(db_path, ignore_errors=True)

    summary = {
        "overall_pass": verification.get("overall_pass", False),
        "criteria": {
            name: {key: value for key, value in data.items() if key in {"pass", "skipped", "error"}}
            if isinstance(data, dict)
            else data
            for name, data in verification.get("criteria", {}).items()
        },
        "report": str(settings.artifacts_dir / "run" / "verification.json"),
    }
    if verification.get("error"):
        summary["error"] = verification["error"]
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if verification.get("overall_pass") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sdd-context verify",
        description="Run the full SDD context verification and write the evidence chain.",
    )
    parser.add_argument(
        "--skip-minimax",
        action="store_true",
        help="verify only the context/state pipeline; MiniMax criteria will fail",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="maximum MiniMax repair attempts (default: 2)",
    )
    args = parser.parse_args(argv)
    return run_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
