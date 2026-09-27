import argparse
import asyncio
import sys
from dataclasses import dataclass

import numpy as np
from app.config import Settings
from app.llm.client import (
    GatewayConfigurationError,
    GatewayOutputError,
    create_gateway_client,
    request_smoke_acknowledgement,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from scripts.make_sample_pdfs import validate_pdf
from scripts.sample_data import PDF_DIR, PolicyData, load_data, validate_dataset


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def check_pdfs() -> CheckResult:
    summary = validate_dataset()
    policies = load_data("policies.yaml", PolicyData)
    for organization in policies.organizations:
        for document in organization.documents:
            path = PDF_DIR / organization.slug / document.filename
            if not path.is_file():
                raise FileNotFoundError("Sample PDF missing; run scripts.make_sample_pdfs first.")
            validate_pdf(path, document)
    return CheckResult(
        "pdfs",
        True,
        f"{summary.documents} PDFs, {summary.pages} pages; "
        f"{summary.evaluation_cases} held-out cases; "
        f"classifier train/validation = {summary.training_examples}/{summary.validation_examples}",
    )


def check_local_models(settings: Settings) -> CheckResult:
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    settings.models_cache_dir.mkdir(parents=True, exist_ok=True)
    supported = [
        model
        for model in TextEmbedding.list_supported_models()
        if model["model"] == settings.embedding_model
    ]
    if not supported:
        raise ValueError("EMBEDDING_MODEL is not supported by the installed FastEmbed version.")
    query = "Which scholarships can be combined with a merit scholarship?"
    documents = [
        "Only need-based scholarships may be combined with the merit scholarship.",
        "Delivery vans must be serviced every ten thousand miles.",
    ]
    embedding = TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=str(settings.models_cache_dir),
        threads=settings.model_threads,
        providers=["CPUExecutionProvider"],
        cuda=False,
    )
    vectors = np.asarray(list(embedding.embed([query, *documents])))
    expected_shape = (3, supported[0]["dim"])
    if vectors.shape != expected_shape or not np.isfinite(vectors).all():
        raise ValueError(f"Embedding shape/values invalid; expected {expected_shape}.")
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0):
        raise ValueError("Embedding model produced a zero vector.")
    similarities = vectors[1:] @ vectors[0] / (norms[1:] * norms[0])
    if similarities[0] <= similarities[1]:
        raise ValueError("Embedding model did not rank relevant evidence above unrelated text.")
    reranker = TextCrossEncoder(
        model_name=settings.reranker_model,
        cache_dir=str(settings.models_cache_dir),
        threads=settings.model_threads,
        providers=["CPUExecutionProvider"],
        cuda=False,
    )
    scores = np.asarray(list(reranker.rerank(query, documents)))
    if scores.shape != (2,) or not np.isfinite(scores).all() or scores[0] <= scores[1]:
        raise ValueError(
            "Re-ranker did not produce two finite, correctly ordered relevance scores."
        )
    return CheckResult(
        "local-models",
        True,
        f"CPU embeddings {vectors.shape}; relevant/unrelated cosine "
        f"{similarities[0]:.3f}/{similarities[1]:.3f}; "
        f"re-ranker {scores[0]:.3f}/{scores[1]:.3f}",
    )


def gateway_http_hint(status: int) -> str:
    hints = {
        400: "check model, JSON response mode and token parameter",
        401: "check the API key",
        403: "check key permissions and gateway access restrictions",
        404: "check base URL/API style and model or deployment name",
        429: "check rate limits and available quota",
    }
    return hints.get(status, "check gateway availability and supported request parameters")


async def check_gateway(settings: Settings) -> list[CheckResult]:
    roles = {
        "fast": settings.llm_fast_model,
        "answer": settings.llm_answer_model,
        "fallback": settings.llm_fallback_model,
    }
    results: list[CheckResult] = []
    checked: dict[str, CheckResult] = {}
    async with create_gateway_client(settings) as client:
        for role, model in roles.items():
            if model in checked:
                prior = checked[model]
                results.append(
                    CheckResult(f"gateway-{role}", prior.passed, "Same model as prior check")
                )
                continue
            try:
                await request_smoke_acknowledgement(client, settings, model)
            except APITimeoutError:
                result = CheckResult(
                    f"gateway-{role}", False, "Gateway request timed out; no retry."
                )
            except APIConnectionError:
                result = CheckResult(
                    f"gateway-{role}",
                    False,
                    "Connection failed; check base URL, network and TLS trust.",
                )
            except APIStatusError as error:
                result = CheckResult(
                    f"gateway-{role}",
                    False,
                    f"HTTP {error.status_code}: {gateway_http_hint(error.status_code)}; no retry.",
                )
            except GatewayOutputError as error:
                result = CheckResult(f"gateway-{role}", False, str(error))
            else:
                result = CheckResult(
                    f"gateway-{role}",
                    True,
                    f"Typed JSON validated ({settings.llm_api_style}, "
                    f"{settings.llm_response_mode}, {settings.llm_token_parameter}); one request.",
                )
            checked[model] = result
            results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit, independently selectable P0 stack checks."
    )
    parser.add_argument("--pdfs", action="store_true", help="Validate generated PDFs and test data")
    parser.add_argument(
        "--local-models", action="store_true", help="Download/run CPU models locally"
    )
    parser.add_argument(
        "--gateway", action="store_true", help="Test each distinct configured model"
    )
    parser.add_argument(
        "--allow-paid", action="store_true", help="Acknowledge possible gateway charges"
    )
    arguments = parser.parse_args()
    if not any((arguments.pdfs, arguments.local_models, arguments.gateway)):
        parser.error("Select --pdfs, --local-models, and/or --gateway.")
    if arguments.gateway and not arguments.allow_paid:
        parser.error("--gateway requires --allow-paid; no gateway requests were made.")
    try:
        settings = Settings()
    except ValidationError as error:
        print(f"FAIL configuration: {error}", file=sys.stderr)
        return 1
    results: list[CheckResult] = []
    if arguments.pdfs:
        try:
            results.append(check_pdfs())
        except (OSError, ValueError) as error:
            results.append(CheckResult("pdfs", False, str(error)))
    if arguments.local_models:
        try:
            results.append(check_local_models(settings))
        except (OSError, ValueError, RuntimeError) as error:
            results.append(CheckResult("local-models", False, str(error)))
    if arguments.gateway:
        try:
            results.extend(asyncio.run(check_gateway(settings)))
        except GatewayConfigurationError as error:
            results.append(CheckResult("gateway", False, str(error)))
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'} {result.name}: {result.detail}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
