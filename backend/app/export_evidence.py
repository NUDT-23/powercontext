from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
EVIDENCE_DIR = Path("/app/evidence")
if not EVIDENCE_DIR.exists():
    EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "evidence"
PROJECT_ID = "demo"


def main() -> None:
    for name in ["qoder", "powercontext", "seekdb", "usage", "demo", "verification"]:
        (EVIDENCE_DIR / name).mkdir(parents=True, exist_ok=True)

    client = httpx.Client(timeout=120.0)
    usage = client.get(f"{BASE_URL}/api/export/usage", params={"project_id": PROJECT_ID}).json()
    stats = client.get(f"{BASE_URL}/api/stats", params={"project_id": PROJECT_ID}).json()
    memory = client.get(f"{BASE_URL}/api/memory", params={"project_id": PROJECT_ID}).json()
    papers = client.get(f"{BASE_URL}/api/papers", params={"project_id": PROJECT_ID}).json()

    (EVIDENCE_DIR / "usage" / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EVIDENCE_DIR / "usage" / "memory_snapshot.json").write_text(
        json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (EVIDENCE_DIR / "usage" / "papers_snapshot.json").write_text(
        json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (EVIDENCE_DIR / "usage" / "events.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["id", "project_id", "user_name", "action", "query", "latency_ms", "result_count", "created_at"]
        )
        for row in usage.get("events", []):
            writer.writerow(
                [
                    row.get("id"),
                    row.get("project_id"),
                    row.get("user_name"),
                    row.get("action"),
                    row.get("query"),
                    row.get("latency_ms"),
                    row.get("result_count"),
                    row.get("created_at"),
                ]
            )

    with (EVIDENCE_DIR / "usage" / "feedback.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "project_id", "user_name", "paper_id", "rating", "relevant", "comment", "created_at"])
        for row in usage.get("feedback", []):
            writer.writerow(
                [
                    row.get("id"),
                    row.get("project_id"),
                    row.get("user_name"),
                    row.get("paper_id"),
                    row.get("rating"),
                    row.get("relevant"),
                    row.get("comment"),
                    row.get("created_at"),
                ]
            )

    for filename, target in [
        ("seekdb_search_trace.jsonl", "seekdb/seekdb_search_trace.jsonl"),
        ("powercontext_trace.jsonl", "powercontext/powercontext_trace.jsonl"),
        ("seed_summary.json", "seekdb/seed_summary.json"),
    ]:
        source = DATA_DIR / filename
        if source.exists():
            shutil.copy2(source, EVIDENCE_DIR / target)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": PROJECT_ID,
        "papers": len(papers.get("papers", [])),
        "events": len(usage.get("events", [])),
        "feedback": len(usage.get("feedback", [])),
        "memories": len(memory.get("memories", [])),
        "files": sorted(
            str(path.relative_to(EVIDENCE_DIR))
            for path in EVIDENCE_DIR.rglob("*")
            if path.is_file()
        ),
    }
    (EVIDENCE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
