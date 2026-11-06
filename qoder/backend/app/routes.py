from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .ingest import ingest_arxiv, ingest_pdf


router = APIRouter(prefix="/api")


class PreferencesIn(BaseModel):
    language: str = "中文"
    style: str = "先给结论，再给证据"
    focus: str = ""
    venues_avoid: str = ""


class ProjectCreate(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    research_question: str = ""
    preferences: PreferencesIn | None = None


class ArxivImport(BaseModel):
    project_id: str
    url: str


class SearchRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1)
    keyword: str | None = None
    year_min: int | None = None
    venue: str | None = None
    n_results: int = 8
    memory_enabled: bool = True
    user_name: str = "anonymous"


class SynthesisRequest(BaseModel):
    project_id: str
    paper_ids: list[str]
    question: str = Field(min_length=1)
    memory_enabled: bool = True
    user_name: str = "anonymous"


class MemoryCreate(BaseModel):
    project_id: str
    text: str = Field(min_length=1)
    kind: str = "preference"
    reason: str = ""


class MemoryForget(BaseModel):
    project_id: str
    artifact: dict[str, Any]
    state_version: int


class FeedbackIn(BaseModel):
    project_id: str
    rating: int | None = None
    relevant: bool | None = None
    comment: str = ""
    paper_id: str | None = None
    user_name: str = "anonymous"


class ReadStatusIn(BaseModel):
    read_status: int = 1


def state(request: Request):
    return request.app.state


@router.get("/health")
def health(request: Request) -> dict:
    app_state = state(request)
    paper_count = app_state.store.db.scalar("SELECT COUNT(*) FROM papers")
    return {
        "status": "ok",
        "seekdb": {
            "papers": int(paper_count or 0),
            "collection": app_state.settings.collection_name,
            "embedding": app_state.embedding_provider,
        },
        "powercontext": app_state.powercontext.health(),
        "llm_configured": app_state.llm.configured,
    }


@router.post("/projects")
def create_project(payload: ProjectCreate, request: Request) -> dict:
    app_state = state(request)
    store = app_state.store
    if payload.id:
        existing = store.get_project(payload.id)
        if existing:
            return {**existing, "warnings": []}

    project = store.create_project(
        name=payload.name,
        description=payload.description,
        research_question=payload.research_question,
        project_id=payload.id,
    )
    warnings: list[str] = []
    try:
        scope_id = app_state.powercontext.ensure_scope(
            project["id"], payload.name, payload.research_question or payload.description
        )
        store.set_scope(project["id"], scope_id)
        if payload.preferences:
            preferences = [
                ("创作语言", payload.preferences.language),
                ("输出风格", payload.preferences.style),
                ("研究关注点", payload.preferences.focus),
                ("回避的期刊/方法", payload.preferences.venues_avoid),
            ]
            for label, value in preferences:
                if value:
                    app_state.powercontext.remember(
                        scope_id,
                        text=f"{label}：{value}",
                        kind="preference",
                        reason="PaperLens 项目初始化偏好",
                    )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"PowerContext 初始化失败：{exc}")

    return {**store.get_project(project["id"]), "warnings": warnings}


@router.get("/projects")
def list_projects(request: Request) -> dict:
    return {"projects": state(request).store.list_projects()}


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict:
    project = state(request).store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/papers/import_arxiv")
def import_arxiv(payload: ArxivImport, request: Request) -> dict:
    app_state = state(request)
    started = time.perf_counter()
    try:
        paper = ingest_arxiv(app_state.store, payload.project_id, payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    app_state.store.log_event(
        payload.project_id, "import_arxiv", payload.url, latency_ms, 1
    )
    return paper


@router.post("/papers/upload")
def upload_paper(
    request: Request,
    project_id: str = Form(...),
    file: UploadFile = File(...),
    title: str = Form(""),
    authors: str = Form(""),
    year: int | None = Form(None),
    venue: str = Form(""),
) -> dict:
    app_state = state(request)
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    started = time.perf_counter()
    try:
        paper = ingest_pdf(
            app_state.store,
            project_id,
            file.filename or "paper.pdf",
            data,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败：{exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    app_state.store.log_event(project_id, "upload_pdf", file.filename or "", latency_ms, 1)
    return paper


@router.get("/papers")
def list_papers(project_id: str, request: Request) -> dict:
    return {"papers": state(request).store.list_papers(project_id)}


@router.patch("/papers/{paper_id}/read")
def update_read_status(paper_id: str, payload: ReadStatusIn, request: Request) -> dict:
    app_state = state(request)
    paper = app_state.store.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")
    app_state.store.update_read_status(paper_id, payload.read_status)
    project = app_state.store.get_project(paper["project_id"])
    scope_id = (project or {}).get("scope_id")
    if scope_id:
        try:
            if payload.read_status:
                app_state.powercontext.remember(
                    scope_id,
                    text=f"已读文献：{paper['title']}",
                    kind="progress",
                    reason="用户在文献库标记已读",
                )
            else:
                app_state.powercontext.capture_source(
                    scope_id,
                    source_id=f"unread-{paper_id}-{uuid.uuid4().hex[:8]}",
                    content=f"用户取消已读标记：{paper['title']}",
                    metadata={"origin": "paperlens-library"},
                )
        except Exception:  # noqa: BLE001
            pass
    app_state.store.log_event(paper["project_id"], "mark_read", paper["title"], 0, 1)
    return app_state.store.get_paper(paper_id) or {}


@router.post("/search")
def search(payload: SearchRequest, request: Request) -> dict:
    app_state = state(request)
    return app_state.search_service.search(
        project_id=payload.project_id,
        query=payload.query,
        keyword=payload.keyword,
        year_min=payload.year_min,
        venue=payload.venue,
        n_results=payload.n_results,
        memory_enabled=payload.memory_enabled,
        user_name=payload.user_name,
    )


@router.post("/synthesize")
def synthesize(payload: SynthesisRequest, request: Request) -> StreamingResponse:
    app_state = state(request)

    def event_stream():
        for event in app_state.synth_service.stream(
            project_id=payload.project_id,
            paper_ids=payload.paper_ids,
            question=payload.question,
            memory_enabled=payload.memory_enabled,
            user_name=payload.user_name,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/memory")
def list_memory(project_id: str, request: Request) -> dict:
    app_state = state(request)
    project = app_state.store.get_project(project_id)
    if not project or not project.get("scope_id"):
        return {"scope_id": None, "memories": []}
    try:
        memories = app_state.powercontext.list_memory(project["scope_id"])
    except Exception as exc:  # noqa: BLE001
        return {"scope_id": project["scope_id"], "memories": [], "error": str(exc)}
    return {"scope_id": project["scope_id"], "memories": memories}


@router.post("/memory/remember")
def remember(payload: MemoryCreate, request: Request) -> dict:
    app_state = state(request)
    project = app_state.store.get_project(payload.project_id)
    if not project or not project.get("scope_id"):
        raise HTTPException(status_code=400, detail="项目未初始化 PowerContext Scope")
    result = app_state.powercontext.remember(
        project["scope_id"], payload.text, kind=payload.kind, reason=payload.reason
    )
    app_state.store.log_event(payload.project_id, "memory_remember", payload.text, 0, 1)
    return {"scope_id": project["scope_id"], "result": result}


@router.post("/memory/forget")
def forget(payload: MemoryForget, request: Request) -> dict:
    app_state = state(request)
    project = app_state.store.get_project(payload.project_id)
    if not project or not project.get("scope_id"):
        raise HTTPException(status_code=400, detail="项目未初始化 PowerContext Scope")
    result = app_state.powercontext.forget(
        project["scope_id"], payload.artifact, payload.state_version
    )
    app_state.store.log_event(payload.project_id, "memory_forget", "", 0, 1)
    return result


@router.post("/feedback")
def feedback(payload: FeedbackIn, request: Request) -> dict:
    app_state = state(request)
    app_state.store.add_feedback(
        payload.project_id,
        rating=payload.rating,
        relevant=1 if payload.relevant else (0 if payload.relevant is False else None),
        comment=payload.comment,
        paper_id=payload.paper_id,
        user_name=payload.user_name,
    )
    app_state.store.log_event(
        payload.project_id, "feedback", payload.comment[:200], 0, 1, payload.user_name
    )
    project = app_state.store.get_project(payload.project_id)
    scope_id = (project or {}).get("scope_id")
    if scope_id and (payload.comment or payload.relevant is not None):
        try:
            text_parts = []
            if payload.relevant is not None:
                text_parts.append("用户认为该结果相关" if payload.relevant else "用户认为该结果不相关")
            if payload.comment:
                text_parts.append(f"反馈：{payload.comment}")
            app_state.powercontext.remember(
                scope_id,
                text="；".join(text_parts),
                kind="feedback",
                reason="用户在检索结果上提交反馈",
            )
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


@router.get("/stats")
def stats(project_id: str, request: Request) -> dict:
    return state(request).store.stats(project_id)


@router.post("/dev/seed")
def dev_seed(request: Request) -> dict:
    from .seed_data import seed

    return seed(state(request))


@router.get("/export/usage")
def export_usage(project_id: str, request: Request) -> dict:
    store = state(request).store
    events = store.db.query(
        "SELECT id, project_id, user_name, action, query, latency_ms, result_count, created_at "
        "FROM events WHERE project_id = %s ORDER BY id",
        (project_id,),
    )
    feedback = store.db.query(
        "SELECT id, project_id, user_name, paper_id, rating, relevant, comment, created_at "
        "FROM feedback WHERE project_id = %s ORDER BY id",
        (project_id,),
    )
    return {"events": events, "feedback": feedback}
