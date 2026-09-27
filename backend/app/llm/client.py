from typing import Literal

from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.chat.completion_create_params import CompletionCreateParamsNonStreaming
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings


class GatewayConfigurationError(ValueError):
    pass


class GatewayOutputError(ValueError):
    pass


class SmokeAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]


def create_gateway_client(settings: Settings) -> AsyncOpenAI:
    if not settings.gateway_configured or settings.llm_base_url is None:
        raise GatewayConfigurationError("Set LLM_BASE_URL and LLM_API_KEY in backend/.env first.")
    if settings.llm_api_style == "azure":
        if not settings.llm_api_version:
            raise GatewayConfigurationError("Azure mode requires LLM_API_VERSION.")
        return AsyncAzureOpenAI(
            azure_endpoint=str(settings.llm_base_url),
            api_version=settings.llm_api_version,
            api_key=settings.llm_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
    return AsyncOpenAI(
        base_url=str(settings.llm_base_url),
        api_key=settings.llm_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )


async def request_smoke_acknowledgement(
    client: AsyncOpenAI, settings: Settings, model: str
) -> SmokeAcknowledgement:
    parameters: CompletionCreateParamsNonStreaming = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": 'Return only this JSON object: {"status":"ok"}.'}],
    }
    if settings.llm_response_mode == "json_schema":
        parameters["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "smoke_acknowledgement",
                "strict": True,
                "schema": SmokeAcknowledgement.model_json_schema(),
            },
        }
    else:
        parameters["response_format"] = {"type": "json_object"}
    if settings.llm_token_parameter == "max_completion_tokens":
        parameters["max_completion_tokens"] = settings.llm_max_output_tokens
    else:
        parameters["max_tokens"] = settings.llm_max_output_tokens

    response = await client.chat.completions.create(**parameters)
    if not response.choices:
        raise GatewayOutputError("Gateway returned no completion choices.")
    choice = response.choices[0]
    if choice.finish_reason != "stop" or choice.message.refusal or not choice.message.content:
        raise GatewayOutputError("Gateway returned an incomplete, refused, or empty completion.")
    try:
        return SmokeAcknowledgement.model_validate_json(choice.message.content)
    except ValidationError as error:
        raise GatewayOutputError(
            "Gateway output did not match the requested JSON schema."
        ) from error
