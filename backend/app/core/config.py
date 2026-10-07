from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="TRACE_", extra="ignore")

    db_path: Path = BACKEND_DIR.parent / "data" / "trace.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "TRACE_GEMINI_API_KEY")
    )
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    llm_timeout_s: float = 45.0

    graph_backend: Literal["networkx", "neo4j"] = "networkx"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "trace-password"

    embedder: Literal["fastembed", "tfidf"] = "fastembed"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    min_reviews: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
