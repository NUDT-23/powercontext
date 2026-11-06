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
EVENT_COLUMNS = ["id", "project_id", "user_name", "action", "query", "latency_ms", "result_count", "created_at"]
FEEDBACK_COLUMNS = ["id", "project_id", "user_name", "paper_id", "rating", "relevant", "comment", "created_at"]


def write_events(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(EVENT_COLUMNS)
        for row in rows:
            writer.writerow([row.get(column) for column in EVENT_COLUMNS])


def write_feedback(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FEEDBACK_COLUMNS)
        for row in rows:
            writer.writerow([row.get(column) for column in FEEDBACK_COLUMNS])


def main() -> None:
    for name in ["qoder", "powercontext", "seekdb", "usage", "usage/trial", "demo", "verification"]:
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

    write_events(EVIDENCE_DIR / "usage" / "events.csv", usage.get("events", []))
    write_feedback(EVIDENCE_DIR / "usage" / "feedback.csv", usage.get("feedback", []))

    projects = client.get(f"{BASE_URL}/api/projects").json().get("projects", [])
    trial_projects = [item for item in projects if str(item.get("id", "")).startswith("trial-")]
    trial_events: list[dict] = []
    trial_feedback: list[dict] = []
    for project in trial_projects:
        trial_usage = client.get(
            f"{BASE_URL}/api/export/usage", params={"project_id": project["id"]}
        ).json()
        trial_events.extend(trial_usage.get("events", []))
        trial_feedback.extend(trial_usage.get("feedback", []))
    trial_summary = client.get(f"{BASE_URL}/api/dev/trial_summary").json()

    if trial_projects:
        write_events(EVIDENCE_DIR / "usage" / "trial" / "trial_events.csv", trial_events)
        write_feedback(EVIDENCE_DIR / "usage" / "trial" / "trial_feedback.csv", trial_feedback)
        (EVIDENCE_DIR / "usage" / "trial" / "trial_summary.json").write_text(
            json.dumps(trial_summary, ensure_ascii=False, indent=2), encoding="utf-8"
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
        "trial_users": trial_summary.get("totals", {}).get("users", 0),
        "trial_events": len(trial_events),
        "trial_feedback": len(trial_feedback),
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
