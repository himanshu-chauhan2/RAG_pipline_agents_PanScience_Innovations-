from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document


class IndexReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexedChunk:
    id: str
    document_id: str
    document_name: str
    page: int
    text: str
    embedding: NDArray[np.float32]


def load_ready_chunks(db: Session, org_id: str, model_name: str) -> list[IndexedChunk]:
    rows = db.execute(
        select(Document, Chunk)
        .outerjoin(Chunk, (Chunk.document_id == Document.id) & (Chunk.org_id == Document.org_id))
        .where(Document.org_id == org_id, Document.status == "ready")
        .order_by(Document.id, Chunk.ordinal)
    ).all()
    result: list[IndexedChunk] = []
    counts: dict[str, int] = {}
    for document, chunk in rows:
        if document.embedding_model != model_name:
            raise IndexReadError(
                "The embedding model changed. Replace the affected PDFs to reindex them."
            )
        if chunk is None or chunk.org_id != org_id or len(chunk.embedding) % 4:
            raise IndexReadError("A ready document has an incomplete index. Replace it to reindex.")
        vector = np.frombuffer(chunk.embedding, dtype="<f4").copy()
        if (
            vector.size != document.embedding_dimensions
            or not np.isfinite(vector).all()
            or not np.any(vector)
        ):
            raise IndexReadError(
                "A stored embedding is invalid. Replace the affected PDF to reindex it."
            )
        result.append(
            IndexedChunk(chunk.id, document.id, document.name, chunk.page, chunk.text, vector)
        )
        counts[document.id] = counts.get(document.id, 0) + 1
    if any(counts.get(document.id) != document.chunk_count for document, _ in rows):
        raise IndexReadError("A ready document has an incomplete index. Replace it to reindex.")
    return result
