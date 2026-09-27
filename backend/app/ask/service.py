import logging
from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.ask.limits import TokenBucket
from app.ask.schemas import (
    AskRequest,
    AskResponse,
    Citation,
    Classification,
    Decision,
    DecisionCheck,
    TraceStep,
)
from app.db import Database
from app.decisions.rules import (
    FOLLOW_UPS,
    Conversation,
    MissingEvidence,
    RuleOutcome,
    Span,
    classify,
    evaluate,
)
from app.errors import ApiError
from app.kb.embeddings import Embedder
from app.kb.index import IndexedChunk, IndexReadError, load_ready_chunks
from app.llm.answer import (
    AnswerGenerator,
    GatewayCallError,
    GatewayUnavailableError,
    SourceText,
)
from app.llm.client import GatewayConfigurationError, GatewayOutputError
from app.models import Assistant, QuestionLog
from app.retrieval.search import Reranker, RetrievalResult, retrieve
from app.retrieval.text import is_verbatim, tokens

logger = logging.getLogger(__name__)

ANSWERABLE_RELEVANCE = 0.2  # calibrated on sample data: relevant >= 0.9, off-topic <= 0.03
SOURCE_RELEVANCE = 0.05
NO_EVIDENCE = (
    "I could not find this in your organisation's uploaded documents, so I cannot answer it."
)


def pending_field(history: Sequence[tuple[str, str]]) -> str | None:
    last_assistant = next((c for r, c in reversed(history) if r == "assistant"), None)
    if last_assistant is None:
        return None
    return next((name for name, text in FOLLOW_UPS.items() if text in last_assistant), None) or (
        "gpa" if "gpa" in last_assistant.lower() else None
    )


class CitationBook:
    def __init__(self) -> None:
        self.items: list[Citation] = []
        self._keys: dict[tuple[str, str], str] = {}

    def add(self, chunk: IndexedChunk, quote: str) -> str:
        key = (chunk.id, quote)
        if key not in self._keys:
            self._keys[key] = f"S{len(self.items) + 1}"
            self.items.append(
                Citation(
                    id=self._keys[key],
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    page=chunk.page,
                    quote=quote,
                )
            )
        return self._keys[key]

    def add_spans(self, spans: Sequence[Span]) -> list[str]:
        return [self.add(span.chunk, span.quote) for span in spans]


class AskService:
    def __init__(
        self,
        database: Database,
        embedder: Embedder,
        reranker: Reranker,
        generator: AnswerGenerator,
        *,
        request_limit: TokenBucket | None = None,
        answer_limit: TokenBucket | None = None,
    ) -> None:
        self.database = database
        self.embedder = embedder
        self.reranker = reranker
        self.generator = generator
        # Local search is cheap and bounded; paid gateway answers get the tighter budget.
        self.request_limit = request_limit or TokenBucket(60, 60, "questions")
        self.answer_limit = answer_limit or TokenBucket(10, 60, "generated answers")

    def _resolve(self, token: str) -> str:
        with self.database.session_factory() as db:
            org_id = db.scalar(select(Assistant.org_id).where(Assistant.token == token))
        if org_id is None:
            raise ApiError(401, "invalid_assistant_token", "This assistant link is not valid.")
        return org_id

    def _load(self, org_id: str) -> list[IndexedChunk]:
        with self.database.session_factory() as db:
            try:
                return load_ready_chunks(db, org_id, self.embedder.model_name)
            except IndexReadError as error:
                raise ApiError(409, "index_unavailable", str(error)) from None

    def _log(self, org_id: str, question: str, response: AskResponse) -> None:
        with self.database.session_factory() as db:
            db.add(
                QuestionLog(
                    id=str(uuid4()),
                    org_id=org_id,
                    question=question,
                    status=response.status,
                    category=response.classification.category,
                )
            )
            db.commit()

    async def ask(self, request: AskRequest) -> AskResponse:
        org_id = await run_in_threadpool(self._resolve, request.token)
        self.request_limit.take(org_id)
        chunks = await run_in_threadpool(self._load, org_id)
        history = [(turn.role, turn.content) for turn in request.history]
        trace = [
            TraceStep(
                step="tenant",
                status="ok",
                detail=f"Resolved assistant token; {len(chunks)} ready chunks in this tenant.",
            )
        ]
        response = await self._answer(org_id, request.question, history, chunks, trace)
        await run_in_threadpool(self._log, org_id, request.question, response)
        return response

    async def _answer(
        self,
        org_id: str,
        question: str,
        history: list[tuple[str, str]],
        chunks: list[IndexedChunk],
        trace: list[TraceStep],
    ) -> AskResponse:
        if not chunks:
            trace.append(TraceStep(step="retrieve", status="skipped", detail="No ready documents."))
            return self._no_answer(trace)

        prior_user = " ".join(content for role, content in history if role == "user")
        conversation = Conversation(question, question, None)
        outcome = evaluate(conversation, chunks)
        pending = pending_field(history)
        if outcome is None and pending and prior_user:
            conversation = Conversation(question, f"{prior_user} {question}", pending)
            outcome = evaluate(conversation, chunks)
        if isinstance(outcome, MissingEvidence):
            trace.append(
                TraceStep(
                    step="rules",
                    status="failed",
                    detail=f"Rule set {outcome.rule_set} matched the question but these policy "
                    f"sentences are not in this organisation's documents: "
                    f"{', '.join(outcome.missing)}.",
                )
            )
            return self._no_answer(trace)
        if isinstance(outcome, RuleOutcome):
            return self._rule_response(outcome, trace, bool(conversation.pending_field))
        trace.append(
            TraceStep(step="rules", status="skipped", detail="No deterministic rule set applies.")
        )
        category = classify(question)
        trace.append(TraceStep(step="classify", status="ok", detail=f"Category: {category}."))

        query = question
        if len(tokens(question)) < 4 and prior_user:
            query = f"{prior_user} {question}"
        try:
            result: RetrievalResult = await run_in_threadpool(
                retrieve, query, chunks, self.embedder, self.reranker
            )
        except Exception as error:
            logger.exception("Retrieval failed")
            raise ApiError(
                503, "retrieval_unavailable", "Local search models are unavailable. Try again."
            ) from error
        trace.append(
            TraceStep(
                step="retrieve",
                status="ok",
                detail=f"Hybrid dense+BM25 search; reranked {result.candidates} candidates; "
                f"top relevance {result.top_relevance:.3f} (threshold {ANSWERABLE_RELEVANCE}).",
            )
        )
        if result.top_relevance < ANSWERABLE_RELEVANCE:
            trace.append(
                TraceStep(step="generate", status="skipped", detail="Evidence below threshold.")
            )
            return self._no_answer(trace, result.top_relevance)

        evidence = [e for e in result.evidence if e.relevance >= SOURCE_RELEVANCE]
        sources = [
            SourceText(f"S{i}", e.chunk.document_name, e.chunk.page, e.chunk.text)
            for i, e in enumerate(evidence, 1)
        ]
        self.answer_limit.take(org_id)
        try:
            generated = await self.generator.generate(question, history, sources)
        except (GatewayUnavailableError, GatewayConfigurationError) as error:
            raise ApiError(
                503, "llm_unavailable", "The answer model is not configured on this server."
            ) from error
        except GatewayCallError as error:
            logger.warning("Answer generation failed: %s", error)
            raise ApiError(502, "llm_failed", str(error)) from error
        except GatewayOutputError as error:
            raise ApiError(502, "llm_invalid_output", str(error)) from error

        if generated.status == "insufficient_evidence":
            trace.append(
                TraceStep(
                    step="generate", status="ok", detail="Model reported insufficient evidence."
                )
            )
            return self._no_answer(trace, result.top_relevance)
        by_id = {source.source_id: evidence[i] for i, source in enumerate(sources)}
        book = CitationBook()
        dropped = 0
        for citation in generated.citations:
            scored = by_id.get(citation.source_id)
            if scored is None or not is_verbatim(citation.quote, scored.chunk.text):
                dropped += 1
                continue
            book.add(scored.chunk, " ".join(citation.quote.split()).strip(" \"'"))
        if not book.items:
            raise ApiError(
                502,
                "ungrounded_answer",
                "The model answer could not be matched to the source documents.",
            )
        trace.append(
            TraceStep(
                step="verify_citations",
                status="ok",
                detail=f"{len(book.items)} verbatim citations kept; {dropped} dropped.",
            )
        )
        return AskResponse(
            status="answered",
            answer=generated.answer,
            references=book.items,
            classification=Classification(category=category),
            confidence=round(result.top_relevance, 3),
            trace=trace,
        )

    @staticmethod
    def _no_answer(trace: list[TraceStep], confidence: float = 0.0) -> AskResponse:
        return AskResponse(
            status="insufficient_evidence",
            answer=NO_EVIDENCE,
            references=[],
            classification=Classification(category="no_answer"),
            confidence=round(confidence, 3),
            trace=trace,
        )

    @staticmethod
    def _rule_response(
        outcome: RuleOutcome, trace: list[TraceStep], used_history: bool
    ) -> AskResponse:
        book = CitationBook()
        checks = [
            DecisionCheck(
                id=c.id,
                label=c.label,
                result=c.result,
                observed=c.observed,
                requirement=c.requirement,
                reference_ids=book.add_spans(c.spans),
            )
            for c in outcome.checks
        ]
        book.add_spans(outcome.notes)
        trace.append(
            TraceStep(
                step="rules",
                status="ok",
                detail=f"Rule set {outcome.rule_set} evaluated {len(checks)} conditions from "
                f"quoted policy text{' using earlier turns' if used_history else ''}: "
                + "; ".join(f"{c.id}={c.result}" for c in checks)
                + f" -> {outcome.verdict}.",
            )
        )
        return AskResponse(
            status="needs_info" if outcome.verdict == "needs_info" else "answered",
            answer=outcome.answer,
            follow_up_question=outcome.follow_up_question,
            references=book.items,
            classification=Classification(category=outcome.category),
            verdict=outcome.verdict,
            decision_trace=Decision(
                rule_set=outcome.rule_set,
                verdict=outcome.verdict,
                checks=checks,
                missing_fields=outcome.missing_fields,
                score=outcome.score,
            ),
            confidence=1.0,
            trace=trace,
        )
