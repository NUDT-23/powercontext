from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    data_dir: str = "/data"
    seekdb_database: str = "paperlens"
    collection_name: str = "paper_chunks"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_provider: str = "auto"
    embedding_batch_size: int = 64

    powercontext_url: str = "http://127.0.0.1:8000"
    powercontext_token: str = ""
    powercontext_timeout: float = 30.0

    cors_origins: str = "*"

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def seekdb_path(self) -> Path:
        path = self.data_path / "seekdb"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def evidence_path(self) -> Path:
        path = Path("/app/evidence")
        if not path.exists():
            path = Path(__file__).resolve().parents[2] / "evidence"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def allow_all_origins(self) -> bool:
        return self.cors_origins.strip() == "*"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.allow_all_origins:
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
