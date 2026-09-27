from __future__ import annotations

from collections.abc import Sequence
from threading import Lock
from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray

from app.config import Settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> NDArray[np.float32]: ...


def normalize_embeddings(
    values: NDArray[np.float32], count: int, dimensions: int
) -> NDArray[np.float32]:
    if count < 1:
        raise ValueError("A document must contain at least one text chunk.")
    matrix = np.asarray(values, dtype=np.float32)
    if dimensions < 1 or matrix.shape != (count, dimensions):
        raise ValueError("The embedding model returned an invalid result shape.")
    if not np.isfinite(matrix).all():
        raise ValueError("The embedding model returned non-finite values.")
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1)
    if np.any(norms == 0):
        raise ValueError("The embedding model returned a zero vector.")
    return (matrix / norms[:, None]).astype(np.float32)


class LocalEmbedder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: TextEmbedding | None = None
        self._lock = Lock()

    @property
    def model_name(self) -> str:
        return self.settings.embedding_model

    @property
    def dimensions(self) -> int:
        from fastembed import TextEmbedding

        for model in TextEmbedding.list_supported_models():
            if model["model"] == self.model_name:
                return int(model["dim"])
        raise ValueError("The configured embedding model is not supported by FastEmbed.")

    def embed_documents(self, texts: Sequence[str]) -> NDArray[np.float32]:
        from fastembed import TextEmbedding

        with self._lock:
            if self._model is None:
                self.settings.models_cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(self.settings.models_cache_dir),
                    threads=self.settings.model_threads,
                    providers=["CPUExecutionProvider"],
                    cuda=False,
                )
            return np.asarray(list(self._model.passage_embed(texts)), dtype=np.float32)
