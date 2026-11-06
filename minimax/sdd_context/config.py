from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _resolve(raw: str | None, default: Path, base: Path) -> Path:
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = base / path
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    package_root: Path
    artifacts_dir: Path
    db_path: Path
    db_name: str
    collection: str
    project_dir: Path
    powercontext_url: str
    scope_id: str | None
    minimax_api_key: str | None
    minimax_base_url: str
    minimax_model: str
    minimax_temperature: float

    @classmethod
    def load(cls) -> "Settings":
        package_root = Path(__file__).resolve().parents[1]
        load_dotenv(package_root / ".env")
        artifacts = _resolve(os.environ.get("SDD_ARTIFACTS_DIR"), package_root / "artifacts", package_root)
        return cls(
            package_root=package_root,
            artifacts_dir=artifacts,
            db_path=_resolve(os.environ.get("SDD_DB_PATH"), artifacts / "seekdb", package_root),
            db_name=os.environ.get("SDD_DB_NAME", "sdd_context"),
            collection=os.environ.get("SDD_COLLECTION", "sdd_documents"),
            project_dir=_resolve(os.environ.get("SDD_PROJECT_DIR"), package_root / "demo_project", package_root),
            powercontext_url=os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:18080").rstrip("/"),
            scope_id=os.environ.get("POWERCONTEXT_SCOPE_ID") or None,
            minimax_api_key=os.environ.get("MINIMAX_API_KEY") or None,
            minimax_base_url=os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1").rstrip("/"),
            minimax_model=os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5"),
            minimax_temperature=float(os.environ.get("MINIMAX_TEMPERATURE", "0.2")),
        )
