"""Application settings.

Everything configurable lives here or in ``config/models.json``. Settings are read from the
environment (and a ``.env`` file at the repo root) so Docker and ``make dev`` share one source.
"""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DEFAULT_MODELS_FILE = BACKEND_DIR / "config" / "models.json"


class ModelPrice(BaseModel):
    """Price per million tokens for one model family (matched by id prefix)."""

    match: str = Field(description="Model id prefix this row applies to, e.g. 'claude-opus-'")
    tier: Literal["capable", "balanced", "cheap", "unknown"] = "unknown"
    input: float
    output: float
    cache_write_5m: float
    cache_read: float


class FallbackModel(BaseModel):
    id: str
    display_name: str


class ModelsConfig(BaseModel):
    """Contents of ``config/models.json``."""

    fallback_models: list[FallbackModel]
    prices: list[ModelPrice]
    tier_hints: dict[str, str] = Field(default_factory=dict)

    def price_for(self, model_id: str) -> ModelPrice | None:
        best: ModelPrice | None = None
        for row in self.prices:
            longer = best is None or len(row.match) > len(best.match)
            if model_id.startswith(row.match) and longer:
                best = row
        return best


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:3000"
    host: str = "0.0.0.0"  # noqa: S104 - container binding, documented in README
    port: int = 8000

    # Storage
    database_url: str = f"sqlite+aiosqlite:///{(REPO_DIR / 'data' / 'codeflow.db').as_posix()}"
    workspace_dir: Path = REPO_DIR / "workspace"
    workspace_retention_days: int = 7

    # Upload limits
    max_upload_mb: int = 200
    max_unzipped_mb: int = 1024
    max_files: int = 20_000
    max_file_bytes: int = 1_000_000
    max_compression_ratio: float = 100.0

    # LLM
    anthropic_api_key: str | None = None  # dev convenience only; prefills the Connect screen
    llm_mode: Literal["anthropic", "mock"] = "anthropic"
    llm_concurrency: int = 4
    max_cost_per_project_usd: float = 5.0
    background_max_nodes: int = 200
    models_config_file: Path = DEFAULT_MODELS_FILE
    default_model_fallbacks: str | None = None  # comma separated ids, overrides models.json list
    key_encryption_secret: str | None = None

    # Rate limits (requests per minute per session/IP)
    rate_limit_uploads_per_minute: int = 6
    rate_limit_analysis_per_minute: int = 20

    @field_validator("workspace_dir", "models_config_file", mode="before")
    @classmethod
    def _expand(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_unzipped_bytes(self) -> int:
        return self.max_unzipped_mb * 1024 * 1024

    @property
    def is_mock(self) -> bool:
        return self.llm_mode == "mock"

    def load_models_config(self) -> ModelsConfig:
        data = json.loads(self.models_config_file.read_text(encoding="utf-8"))
        cfg = ModelsConfig.model_validate(data)
        if self.default_model_fallbacks:
            ids = [m.strip() for m in self.default_model_fallbacks.split(",") if m.strip()]
            cfg.fallback_models = [FallbackModel(id=i, display_name=i) for i in ids]
        return cfg

    def encryption_secret(self) -> str:
        """Return the at-rest secret, generating and persisting one when missing."""
        if self.key_encryption_secret:
            return self.key_encryption_secret
        secret_file = self.workspace_dir / ".key_encryption_secret"
        if secret_file.exists():
            return secret_file.read_text(encoding="utf-8").strip()
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(32)
        secret_file.write_text(secret, encoding="utf-8")
        secret_file.chmod(0o600)
        return secret


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
