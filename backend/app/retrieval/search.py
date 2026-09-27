from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray

from app.config import Settings
from app.kb.embeddings import Embedder
from app.kb.index import IndexedChunk
from app.retrieval.text import tokens

if TYPE_CHECKING:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CANDIDATE_LIMIT = 12
EVIDENCE_LIMIT = 5
RRF_K = 60


class Reranker(Protocol):
    @property
    def model_name(self) -> str: ...

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


class LocalReranker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: TextCrossEncoder | None = None
        self._lock = Lock()

    @property
    def model_name(self) -> str:
        return self.settings.reranker_model

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        with self._lock:
            if self._model is None:
                self.settings.models_cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextCrossEncoder(
                    model_name=self.model_name,
                    cache_dir=str(self.settings.models_cache_dir),
                    threads=self.settings.model_threads,
                    providers=["CPUExecutionProvider"],
                    cuda=False,
                )
            return [float(value) for value in self._model.rerank(query, list(texts))]


@dataclass(frozen=True)
class ScoredChunk:
    chunk: IndexedChunk
    relevance: float  # sigmoid of the cross-encoder logit, 0..1


@dataclass(frozen=True)
class RetrievalResult:
    evidence: list[ScoredChunk]
    candidates: int
    top_relevance: float


def embed_query(embedder: Embedder, query: str) -> NDArray[np.float32]:
    text = BGE_QUERY_PREFIX + query if "bge" in embedder.model_name.lower() else query
    vector = np.asarray(embedder.embed_documents([text]), dtype=np.float32)
    if vector.ndim != 2 or vector.shape[0] != 1 or not np.isfinite(vector).all():
        raise ValueError("The embedding model returned an invalid query vector.")
    norm = float(np.linalg.norm(vector[0]))
    if norm == 0:
        raise ValueError("The embedding model returned a zero query vector.")
    return vector[0] / norm


def bm25_scores(query: str, chunks: Sequence[IndexedChunk]) -> list[float]:
    documents = [tokens(chunk.text) for chunk in chunks]
    query_terms = set(tokens(query))
    if not documents or not query_terms:
        return [0.0] * len(chunks)
    average = sum(len(doc) for doc in documents) / len(documents) or 1.0
    frequency = Counter(term for doc in documents for term in set(doc))
    scores: list[float] = []
    for doc in documents:
        counts = Counter(doc)
        score = 0.0
        for term in query_terms:
            if counts[term]:
                idf = math.log(
                    1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5)
                )
                tf = counts[term]
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / average))
        scores.append(score)
    return scores


def retrieve(
    query: str, chunks: Sequence[IndexedChunk], embedder: Embedder, reranker: Reranker
) -> RetrievalResult:
    """Hybrid dense + BM25 candidates fused with RRF, then one bounded cross-encoder call."""
    if not chunks:
        return RetrievalResult([], 0, 0.0)
    vector = embed_query(embedder, query)
    dense = [
        float(np.dot(chunk.embedding, vector) / np.linalg.norm(chunk.embedding)) for chunk in chunks
    ]
    lexical = bm25_scores(query, chunks)
    fused = [0.0] * len(chunks)
    for scores in (dense, lexical):
        for rank, index in enumerate(sorted(range(len(chunks)), key=lambda i: -scores[i])):
            fused[index] += 1 / (RRF_K + rank + 1)
    candidates = sorted(range(len(chunks)), key=lambda i: -fused[i])[:CANDIDATE_LIMIT]
    logits = reranker.score(query, [chunks[i].text for i in candidates])
    if len(logits) != len(candidates) or not all(math.isfinite(v) for v in logits):
        raise ValueError("The reranker returned an invalid result.")
    scored = sorted(
        (
            ScoredChunk(chunks[i], 1 / (1 + math.exp(-max(-50.0, min(50.0, logit)))))
            for i, logit in zip(candidates, logits, strict=True)
        ),
        key=lambda item: -item.relevance,
    )
    return RetrievalResult(scored[:EVIDENCE_LIMIT], len(candidates), scored[0].relevance)
