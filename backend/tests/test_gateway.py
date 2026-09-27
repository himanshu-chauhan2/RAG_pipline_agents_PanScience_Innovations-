import asyncio
import json

import httpx
import pytest
from app.config import Settings
from app.llm.client import (
    GatewayConfigurationError,
    GatewayOutputError,
    SmokeAcknowledgement,
    create_gateway_client,
    request_smoke_acknowledgement,
)
from openai import APIStatusError, AsyncOpenAI

from scripts import smoke_test


def settings_for_test(**overrides: object) -> Settings:
    values = {
        "llm_base_url": "https://gateway.example.test/v1",
        "llm_api_key": "test-key",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def completion(content: str = '{"status":"ok"}', finish_reason: str = "stop") -> dict[str, object]:
    return {
        "id": "test-completion",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }


def request_with_mock(
    settings: Settings,
    response: dict[str, object],
    seen: list[httpx.Request],
    status: int = 200,
) -> SmokeAcknowledgement:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=response)

    async def run() -> SmokeAcknowledgement:
        async with AsyncOpenAI(
            api_key="test-key",
            base_url="https://gateway.example.test/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ) as client:
            return await request_smoke_acknowledgement(client, settings, "test-model")

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["json_schema", "json"])
@pytest.mark.parametrize("token_parameter", ["max_completion_tokens", "max_tokens"])
def test_request_format_is_explicit_and_typed(mode: str, token_parameter: str) -> None:
    settings = settings_for_test(llm_response_mode=mode, llm_token_parameter=token_parameter)
    seen: list[httpx.Request] = []
    assert request_with_mock(settings, completion(), seen).status == "ok"
    assert len(seen) == 1
    payload = json.loads(seen[0].content)
    assert payload["response_format"]["type"] == (
        "json_schema" if mode == "json_schema" else "json_object"
    )
    assert payload[token_parameter] == 1024
    assert "temperature" not in payload
    unused_parameter = (
        "max_tokens" if token_parameter == "max_completion_tokens" else "max_completion_tokens"
    )
    assert unused_parameter not in payload
    if mode == "json_schema":
        schema = payload["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False


@pytest.mark.parametrize("content", ["not JSON", '{"status":"wrong"}', '{"status":"ok","extra":1}'])
def test_invalid_model_output_is_not_a_success(content: str) -> None:
    with pytest.raises(GatewayOutputError, match="JSON schema"):
        request_with_mock(settings_for_test(), completion(content), [])


def test_truncated_output_is_rejected_even_if_json_looks_valid() -> None:
    with pytest.raises(GatewayOutputError, match="incomplete"):
        request_with_mock(settings_for_test(), completion(finish_reason="length"), [])


def test_http_errors_are_not_retried_or_converted_to_success() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(APIStatusError):
        request_with_mock(settings_for_test(), {"error": {"message": "quota"}}, seen, status=429)
    assert len(seen) == 1


def test_missing_credentials_fail_before_a_client_is_created() -> None:
    with pytest.raises(GatewayConfigurationError, match="LLM_BASE_URL"):
        create_gateway_client(Settings(_env_file=None))


def test_azure_requires_an_explicit_api_version() -> None:
    with pytest.raises(GatewayConfigurationError, match="LLM_API_VERSION"):
        create_gateway_client(settings_for_test(llm_api_style="azure"))


def test_gateway_check_runs_once_per_distinct_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion())

    def client_factory(settings: Settings) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="test-key",
            base_url="https://gateway.example.test/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(smoke_test, "create_gateway_client", client_factory)
    settings = settings_for_test(
        llm_fast_model="same", llm_answer_model="same", llm_fallback_model="same"
    )
    results = asyncio.run(smoke_test.check_gateway(settings))
    assert len(results) == 3
    assert all(result.passed for result in results)
    assert len(seen) == 1


def test_gateway_cli_requires_explicit_cost_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["smoke_test", "--gateway"])
    with pytest.raises(SystemExit) as error:
        smoke_test.main()
    assert error.value.code == 2
