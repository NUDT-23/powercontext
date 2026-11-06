from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
EVIDENCE_DIR = Path("/app/evidence")
if not EVIDENCE_DIR.exists():
    EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "evidence"
VERIFY_DIR = EVIDENCE_DIR / "verification"
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

PROJECT_ID = "demo"
results: list[dict] = []


def record(name: str, passed: bool, detail: str) -> None:
    results.append(
        {
            "name": name,
            "passed": passed,
            "detail": detail,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    print(("[PASS] " if passed else "[FAIL] ") + name + " :: " + detail)


def main() -> int:
    client = httpx.Client(timeout=240.0)
    headers = {"Content-Type": "application/json"}

    try:
        health = client.get(f"{BASE_URL}/api/health").json()
        record(
            "health",
            health.get("status") == "ok" and health.get("seekdb", {}).get("papers", 0) >= 20,
            json.dumps(health, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        record("health", False, str(exc))

    try:
        papers = client.get(
            f"{BASE_URL}/api/papers", params={"project_id": PROJECT_ID}
        ).json()["papers"]
        record("seed_corpus", len(papers) >= 20, f"papers={len(papers)}")
    except Exception as exc:  # noqa: BLE001
        papers = []
        record("seed_corpus", False, str(exc))

    try:
        payload = {
            "project_id": PROJECT_ID,
            "query": "How do LLM agents remember, plan and evaluate their work?",
            "n_results": 8,
            "memory_enabled": True,
        }
        search = client.post(f"{BASE_URL}/api/search", json=payload, headers=headers).json()
        found = search.get("results", [])
        has_citation = all(item.get("chunks") and item.get("title") for item in found)
        record(
            "hybrid_search",
            len(found) > 0 and has_citation,
            f"results={len(found)} latency_ms={search.get('latency_ms')}",
        )
        (VERIFY_DIR / "search_sample.json").write_text(
            json.dumps(search, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        record("hybrid_search", False, str(exc))

    try:
        payload = {
            "project_id": PROJECT_ID,
            "query": "agent memory long-term",
            "keyword": "memory",
            "year_min": 2025,
            "n_results": 8,
            "memory_enabled": False,
        }
        search = client.post(f"{BASE_URL}/api/search", json=payload, headers=headers).json()
        found = search.get("results", [])
        years_ok = all(int(item.get("year") or 0) >= 2025 for item in found)
        record(
            "scalar_filter",
            len(found) > 0 and years_ok,
            f"results={len(found)} years={[item.get('year') for item in found]}",
        )
    except Exception as exc:  # noqa: BLE001
        record("scalar_filter", False, str(exc))

    memory_text = "Preference: when searching agent memory topics, prefer survey papers and always cite sources."
    try:
        client.post(
            f"{BASE_URL}/api/memory/remember",
            json={
                "project_id": PROJECT_ID,
                "text": memory_text,
                "kind": "preference",
                "reason": "自动验收脚本写入",
            },
            headers=headers,
        ).raise_for_status()
        listed = client.get(
            f"{BASE_URL}/api/memory", params={"project_id": PROJECT_ID}
        ).json()
        texts = [item.get("text", "") for item in listed.get("memories", [])]
        record("memory_write", any(memory_text in text for text in texts), f"memories={len(texts)}")

        used = []
        for _ in range(5):
            payload = {
                "project_id": PROJECT_ID,
                "query": "agent memory survey cite sources",
                "n_results": 3,
                "memory_enabled": True,
            }
            search = client.post(
                f"{BASE_URL}/api/search", json=payload, headers=headers
            ).json()
            used = search.get("used_memories") or []
            if used:
                break
            time.sleep(1.5)
        record(
            "memory_recall",
            len(used) > 0,
            f"used_memories={len(used)} sample={(used[0]['text'][:80] if used else '')}",
        )

        # Remove the verification memory so repeated runs keep the demo scope tidy.
        try:
            listed = client.get(
                f"{BASE_URL}/api/memory", params={"project_id": PROJECT_ID}
            ).json()
            for item in listed.get("memories", []):
                if item.get("text") != memory_text or not item.get("artifact"):
                    continue
                state_version = item.get("state_version")
                if state_version is None:
                    continue
                client.post(
                    f"{BASE_URL}/api/memory/forget",
                    json={
                        "project_id": PROJECT_ID,
                        "artifact": item["artifact"],
                        "state_version": state_version,
                    },
                    headers=headers,
                )
        except Exception:  # noqa: BLE001 - cleanup must not fail verification
            pass
    except Exception as exc:  # noqa: BLE001
        record("memory_write", False, str(exc))
        record("memory_recall", False, str(exc))

    try:
        paper_ids = [paper["id"] for paper in papers[:3]]
        events: list[dict] = []
        with client.stream(
            "POST",
            f"{BASE_URL}/api/synthesize",
            json={
                "project_id": PROJECT_ID,
                "paper_ids": paper_ids,
                "question": "用一段话总结这些论文在 LLM Agent 记忆或评测上的主要差异，并标注引用。",
                "memory_enabled": True,
            },
            headers=headers,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    continue
        meta = next((event for event in events if event.get("type") == "meta"), None)
        delta_chars = sum(
            len(event.get("content", ""))
            for event in events
            if event.get("type") == "delta"
        )
        done = any(event.get("type") == "done" for event in events)
        record(
            "synthesis_stream",
            meta is not None and delta_chars > 0 and done,
            f"events={len(events)} chars={delta_chars} llm={meta.get('llm_configured') if meta else None}",
        )
        (VERIFY_DIR / "synthesis_events.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        record("synthesis_stream", False, str(exc))

    try:
        seekdb_trace = DATA_DIR / "seekdb_search_trace.jsonl"
        pc_trace = DATA_DIR / "powercontext_trace.jsonl"
        seekdb_records = [
            json.loads(line) for line in seekdb_trace.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        pc_records = [
            json.loads(line) for line in pc_trace.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        ops = {record.get("op") for record in pc_records}
        passed = (
            len(seekdb_records) >= 2
            and len(pc_records) >= 2
            and {"remember", "search_memory"} <= ops
        )
        record(
            "audit_traces",
            passed,
            f"seekdb_records={len(seekdb_records)} pc_records={len(pc_records)} pc_ops={sorted(ops)}",
        )
        (VERIFY_DIR / "seekdb_trace_sample.json").write_text(
            json.dumps(seekdb_records[-3:], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (VERIFY_DIR / "powercontext_trace_sample.json").write_text(
            json.dumps(pc_records[-5:], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        record("audit_traces", False, str(exc))

    passed = all(item["passed"] for item in results)
    summary = {
        "passed": passed,
        "checks": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (VERIFY_DIR / "verify_output.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# PaperLens 自动验收报告", ""]
    lines.append(f"- 结论：{'PASS' if passed else 'FAIL'}")
    lines.append(f"- 时间：{summary['generated_at']}")
    lines.append("")
    lines.append("| 检查项 | 结果 | 详情 |")
    lines.append("| --- | --- | --- |")
    for item in results:
        lines.append(
            f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | {item['detail'][:180]} |"
        )
    (VERIFY_DIR / "verify_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n== VERIFY", "PASS" if passed else "FAIL", "==")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
