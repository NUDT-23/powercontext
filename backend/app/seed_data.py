from __future__ import annotations

import json
from pathlib import Path

from .ingest import chunk_text

SEED_DIR = Path("/app/seed")
FALLBACK_SEED_DIR = Path(__file__).resolve().parents[2] / "seed"

DEMO_PROJECT_ID = "demo"
DEMO_PREFERENCES = [
    ("创作语言", "中文 Chinese，术语保留英文原名"),
    ("输出风格", "简洁，先给结论，再给证据 (conclusion first, evidence backed)"),
    (
        "研究关注点",
        "Research focus: LLM agents, agent memory, long-term memory, planning and plan, "
        "evaluation and evaluate; method comparison, reproducibility, limitations；"
        "方法对比、实验可复现性与局限性",
    ),
    ("回避的期刊/方法", "opinion pieces without experiments；没有实验验证的纯观点文章"),
]


def _seed_file() -> Path:
    path = SEED_DIR / "papers.json"
    return path if path.exists() else FALLBACK_SEED_DIR / "papers.json"


def seed_trial_projects(app_state, users: int = 12) -> dict:
    if users < 1 or users > 50:
        raise ValueError("users must be between 1 and 50")

    store = app_state.store
    powercontext = app_state.powercontext
    papers = json.loads(_seed_file().read_text(encoding="utf-8"))
    projects: list[dict] = []
    warnings: list[str] = []

    for index in range(1, users + 1):
        project_id = f"trial-{index:02d}"
        name = f"试用 U{index:02d} · LLM Agent 文献"
        research_question = "如何比较 LLM Agent 的记忆、规划与评测方法？"
        project = store.get_project(project_id)
        if not project:
            project = store.create_project(
                name=name,
                description="现场试用专用项目，语料与 demo 项目相同。",
                research_question=research_question,
                project_id=project_id,
            )
        if not project.get("scope_id"):
            try:
                scope_id = powercontext.ensure_scope(project_id, name, research_question)
                store.set_scope(project_id, scope_id)
                for label, value in DEMO_PREFERENCES:
                    powercontext.remember(
                        scope_id,
                        text=f"{label}：{value}",
                        kind="preference",
                        reason="PaperLens 试用默认偏好",
                    )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{project_id}: PowerContext 不可用：{exc}")

        added = 0
        for paper in papers:
            if store.paper_exists(project_id, paper["arxiv_id"]):
                continue
            text = f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"
            chunks = chunk_text(text, max_chars=900, overlap=120, section="abstract")
            if not chunks:
                continue
            store.add_paper(project_id, paper, chunks)
            added += 1
        projects.append(
            {
                "project_id": project_id,
                "name": name,
                "added_now": added,
                "papers_total": store.count_papers(project_id),
                "chunks_total": store.count_chunks(project_id),
            }
        )

    return {"users": users, "projects": projects, "warnings": warnings}


def seed(app_state) -> dict:
    store = app_state.store
    powercontext = app_state.powercontext
    settings = app_state.settings

    project = store.get_project(DEMO_PROJECT_ID)
    if not project:
        project = store.create_project(
            name="LLM Agent 与因果推断研究",
            description="PaperLens 演示项目：20 篇 arXiv 公开文献的混合检索与综述示例。",
            research_question="如何比较 LLM Agent 的记忆、规划与评测方法？",
            project_id=DEMO_PROJECT_ID,
        )

    warnings: list[str] = []
    if not project.get("scope_id"):
        try:
            scope_id = powercontext.ensure_scope(
                DEMO_PROJECT_ID,
                project["name"],
                project.get("research_question") or "",
            )
            store.set_scope(DEMO_PROJECT_ID, scope_id)
            for label, value in DEMO_PREFERENCES:
                powercontext.remember(
                    scope_id,
                    text=f"{label}：{value}",
                    kind="preference",
                    reason="PaperLens 演示偏好",
                )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"PowerContext 不可用：{exc}")

    papers = json.loads(_seed_file().read_text(encoding="utf-8"))
    added = 0
    skipped = 0
    for paper in papers:
        if store.paper_exists(DEMO_PROJECT_ID, paper["arxiv_id"]):
            skipped += 1
            continue
        text = f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"
        chunks = chunk_text(text, max_chars=900, overlap=120, section="abstract")
        if not chunks:
            continue
        store.add_paper(DEMO_PROJECT_ID, paper, chunks)
        added += 1

    store.log_event(DEMO_PROJECT_ID, "seed", f"added={added} skipped={skipped}", 0, added)
    summary = {
        "project_id": DEMO_PROJECT_ID,
        "papers_total": store.count_papers(DEMO_PROJECT_ID),
        "chunks_total": store.count_chunks(DEMO_PROJECT_ID),
        "added_now": added,
        "skipped_now": skipped,
        "warnings": warnings,
        "embedding": app_state.embedding_provider,
    }
    try:
        (settings.data_path / "seed_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass
    return summary
