from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


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

    @field_validator("models_cache_dir")
    @classmethod
    def resolve_cache_directory(cls, value: Path) -> Path:
        return value if value.is_absolute() else BACKEND_DIR / value

    @property
    def gateway_configured(self) -> bool:
        return self.llm_base_url is not None and bool(self.llm_api_key.get_secret_value().strip())
