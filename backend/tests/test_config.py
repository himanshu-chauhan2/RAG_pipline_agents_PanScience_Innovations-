import pytest
from pydantic import ValidationError

from app.config import BACKEND_DIR, Settings


def test_empty_gateway_settings_are_explicitly_unconfigured() -> None:
    settings = Settings(_env_file=None, llm_base_url="", llm_api_key="")
    assert settings.llm_base_url is None
    assert not settings.gateway_configured


def test_key_alone_does_not_mean_configured() -> None:
    assert not Settings(_env_file=None, llm_api_key="test-key").gateway_configured


def test_gateway_configuration_does_not_expose_key_in_repr() -> None:
    settings = Settings(
        _env_file=None, llm_base_url="https://gateway.example.test/v1", llm_api_key="test-secret"
    )
    assert settings.gateway_configured
    assert "test-secret" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@gateway.example.test/v1",
        "https://gateway.example.test/v1?api_key=secret",
        "file:///private/path",
    ],
)
def test_credentials_and_non_http_schemes_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, llm_base_url=url)
    assert url not in str(error.value)


def test_cache_directory_is_relative_to_backend_not_shell_directory() -> None:
    settings = Settings(_env_file=None, models_cache_dir=".cache/test-models")
    assert settings.models_cache_dir == BACKEND_DIR / ".cache" / "test-models"


@pytest.mark.parametrize("threads", [0, 9])
def test_cpu_threads_are_bounded(threads: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, model_threads=threads)


def test_unknown_gateway_mode_is_not_silently_replaced() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_response_mode="unsupported")
