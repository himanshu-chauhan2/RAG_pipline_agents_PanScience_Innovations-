from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
SESSION_COOKIE_NAME = "kda_admin"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
    )

    llm_base_url: HttpUrl | None = None
    llm_api_key: SecretStr = SecretStr("")
    llm_fast_model: str = Field(default="gpt-5.6-luna", min_length=1)
    llm_answer_model: str = Field(default="gpt-5.6-terra", min_length=1)
    llm_fallback_model: str = Field(default="gpt-5.1", min_length=1)
    llm_api_style: Literal["openai", "azure"] = "openai"
    llm_api_version: str = ""
    llm_response_mode: Literal["json_schema", "json"] = "json_schema"
    llm_token_parameter: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    llm_max_output_tokens: int = Field(default=1024, ge=128, le=8192)
    llm_timeout_seconds: float = Field(default=45, gt=0, le=180)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    models_cache_dir: Path = BACKEND_DIR / ".cache" / "models"
    model_threads: int = Field(default=2, ge=1, le=8)
    database_path: Path = BACKEND_DIR / "data" / "assistant.db"
    uploads_dir: Path = BACKEND_DIR / "uploads"
    auth_secret_key: SecretStr = SecretStr("")
    auth_secret_file: Path = BACKEND_DIR / "data" / "auth-signing.key"
    auth_session_minutes: int = Field(default=480, ge=1, le=1440)
    auth_cookie_secure: bool = False
    auth_allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def blank_url_is_unconfigured(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_base_url")
    @classmethod
    def reject_credentials_in_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value and (value.username or value.password or value.query or value.fragment):
            raise ValueError("Use a gateway base URL without credentials, query, or fragment")
        return value

    @field_validator("models_cache_dir", "database_path", "auth_secret_file", "uploads_dir")
    @classmethod
    def resolve_backend_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else BACKEND_DIR / value

    @field_validator("auth_secret_key")
    @classmethod
    def require_strong_signing_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value()
        if key and (not key.strip() or len(key.encode("utf-8")) < 32):
            raise ValueError("AUTH_SECRET_KEY must contain at least 32 bytes, or be left empty")
        return value

    @field_validator("auth_allowed_origins")
    @classmethod
    def validate_auth_origins(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("At least one explicit authentication origin is required")
        origins: list[str] = []
        for value in values:
            url = HttpUrl(value)
            if (
                url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in (None, "/")
            ):
                raise ValueError("Authentication origins must contain only scheme, host and port")
            origins.append(str(url).rstrip("/"))
        return list(dict.fromkeys(origins))

    @property
    def gateway_configured(self) -> bool:
        return self.llm_base_url is not None and bool(self.llm_api_key.get_secret_value().strip())
