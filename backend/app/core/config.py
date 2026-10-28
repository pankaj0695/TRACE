import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DB_NAME = "trace.db"


def db_candidates() -> list[Path]:
    """Places the working-set database may live, most specific first.

    The repo layout keeps it in <repo>/data, but people routinely unzip/clone so that it ends up in
    backend/data, next to the process, or one level off. We look in all of them instead of failing.
    """
    roots: list[Path] = []
    if os.environ.get("TRACE_DATA_DIR"):
        roots.append(Path(os.environ["TRACE_DATA_DIR"]).expanduser())
    cwd = Path.cwd()
    roots += [BACKEND_DIR.parent / "data", BACKEND_DIR / "data", cwd / "data", cwd.parent / "data", cwd]
    seen: list[Path] = []
    for root in roots:
        path = (root / DB_NAME).resolve()
        if path not in seen:
            seen.append(path)
    return seen


def default_db_path() -> Path:
    candidates = db_candidates()
    return next((p for p in candidates if p.is_file()), candidates[0])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="TRACE_", extra="ignore")

    db_path: Path = Field(default_factory=default_db_path)
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

    # --- MCP server & governance (see docs/GOVERNANCE.md) -------------------------------------------------
    mcp_enabled: bool = True
    # "token:role:principal" entries, comma separated. Roles: viewer < analyst < reviewer < admin.
    # Tokens are compared in constant time; prefer 32+ random characters.
    mcp_api_keys: str = ""
    # Local development only: lets unauthenticated HTTP clients in with the read-only `viewer` role.
    mcp_allow_anonymous: bool = False
    # Extra browser origins allowed to call /mcp (DNS-rebinding protection). Non-browser clients send no Origin.
    mcp_allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    mcp_rate_limit_per_min: int = 60
    mcp_analysis_rate_limit_per_min: int = 6
    mcp_max_result_chars: int = 60_000
    mcp_stdio_role: Literal["viewer", "analyst", "reviewer", "admin"] = "analyst"

    # --- Data governance (see docs/DATA_GOVERNANCE.md) -------------------------------------------------------
    # Third-party processors cleared to receive data. PROTOTYPE default: gemini and neo4j are pre-approved so the demo
    # works out of the box (redaction, pseudonymisation and the egress ledger still apply). For the production build
    # (local LLM + local database) set this to empty: nothing then leaves the machine.
    approved_processors: str = "gemini,neo4j"
    llm_egress_mode: Literal["off", "redacted"] = "redacted"
    llm_max_prompt_chars: int = 20_000
    retention_analyses_days: int = 365
    retention_egress_days: int = 180
    retention_decisions_days: int = 1095
    retention_audit_days: int = 730

    @field_validator("db_path", mode="after")
    @classmethod
    def _resolve_db_path(cls, value: Path) -> Path:
        value = value.expanduser()
        return (value if value.is_absolute() else BACKEND_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
