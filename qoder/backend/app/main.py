from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .embedding import build_embedding_function
from .llm import LLMClient
from .powercontext import PowerContextClient
from .routes import router
from .search_service import SearchService
from .seekdb_store import SeekDBStore
from .synth_service import SynthesisService


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    embedding_function, embedding_provider = build_embedding_function(settings)
    store = SeekDBStore(settings, embedding_function)
    store.init_schema()
    powercontext = PowerContextClient(settings)
    llm = LLMClient(settings)

    app.state.settings = settings
    app.state.store = store
    app.state.powercontext = powercontext
    app.state.llm = llm
    app.state.embedding_provider = embedding_provider
    app.state.search_service = SearchService(store, powercontext)
    app.state.synth_service = SynthesisService(settings, store, powercontext, llm)
    yield


app = FastAPI(
    title="PaperLens API",
    description="科研文献混合检索 + PowerContext 记忆增强综述助手",
    version="0.1.0",
    lifespan=lifespan,
)

settings_for_cors = Settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_for_cors.cors_origin_list,
    allow_credentials=not settings_for_cors.allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
