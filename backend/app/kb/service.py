import logging
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from threading import BoundedSemaphore, Condition, RLock
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import Database
from app.errors import ApiError
from app.kb.embeddings import Embedder, normalize_embeddings
from app.kb.limits import MAX_CONCURRENT_UPLOADS, MAX_DOCUMENTS, MAX_INDEX_JOBS
from app.kb.pdf import PageChunk, PreparedPdf
from app.kb.schemas import DocumentList, DocumentSummary, summarize_document
from app.kb.storage import PrivateStorage, StorageError
from app.models import Chunk, Document, unix_time

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexJob:
    document_id: str
    org_id: str
    revision: str
    storage_key: str
    name: str
    pages: int
    size_bytes: int
    chunks: tuple[PageChunk, ...]
    warnings: tuple[str, ...]
    replacement: bool


class IndexingService:
    def __init__(self, database: Database, storage: PrivateStorage, embedder: Embedder) -> None:
        self.database = database
        self.storage = storage
        self.embedder = embedder
        self.upload_slots = BoundedSemaphore(MAX_CONCURRENT_UPLOADS)
        self._slots = BoundedSemaphore(MAX_INDEX_JOBS)
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-index")
        self._jobs: dict[str, tuple[IndexJob, Future[None]]] = {}
        self._failed_updates: dict[str, tuple[IndexJob, str, str]] = {}
        self._closed = False

    @contextmanager
    def _write(self) -> Iterator[Session]:
        with self._lock, self.database.session_factory() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield db

    def _document(self, db: Session, org_id: str, document_id: str) -> Document:
        document = db.scalar(
            select(Document).where(Document.id == document_id, Document.org_id == org_id)
        )
        if document is None:
            raise ApiError(404, "document_not_found", "Document not found.")
        return document

    def _flush_failures(self) -> None:
        with self._lock:
            for revision, (job, code, message) in list(self._failed_updates.items()):
                self._mark_failed(job, code, message)
                del self._failed_updates[revision]

    def list_documents(self, org_id: str) -> DocumentList:
        self._flush_failures()
        with self.database.session_factory() as db:
            documents = db.scalars(
                select(Document)
                .where(Document.org_id == org_id)
                .order_by(Document.created_at, Document.id)
            ).all()
            return DocumentList(
                documents=[summarize_document(document) for document in documents],
                used=len(documents),
            )

    def get_document(self, org_id: str, document_id: str) -> DocumentSummary:
        self._flush_failures()
        with self.database.session_factory() as db:
            return summarize_document(self._document(db, org_id, document_id))

    def check_replacement(self, org_id: str, document_id: str) -> None:
        with self.database.session_factory() as db:
            self._require_idle(self._document(db, org_id, document_id))

    @staticmethod
    def _require_idle(document: Document) -> None:
        if document.status == "processing" or document.pending_revision is not None:
            raise ApiError(
                409,
                "document_busy",
                "Wait for this document to finish processing before replacing it.",
            )

    def add_document(
        self, org_id: str, pdf: PreparedPdf, replace_id: str | None = None
    ) -> DocumentSummary:
        self._flush_failures()
        if not self._slots.acquire(blocking=False):
            raise ApiError(503, "processing_busy", "The indexing queue is full. Try again shortly.")
        job: IndexJob | None = None
        key: str | None = None
        stored = False
        submitted = False
        try:
            with self._write() as db:
                if self._closed:
                    raise ApiError(503, "processing_busy", "The indexer is shutting down.")
                if replace_id is None:
                    used = db.scalar(
                        select(func.count()).select_from(Document).where(Document.org_id == org_id)
                    )
                    if used is not None and used >= MAX_DOCUMENTS:
                        raise ApiError(
                            409, "document_limit", "An organisation may store at most 10 PDFs."
                        )
                    document = None
                else:
                    document = self._document(db, org_id, replace_id)
                    self._require_idle(document)
                key = self.storage.create(pdf.content)
                revision = uuid4().hex
                now = unix_time()
                old_pending = document.pending_storage_key if document is not None else None
                with self.storage.reversible_remove([old_pending]):
                    if document is None:
                        document = Document(
                            id=str(uuid4()),
                            org_id=org_id,
                            name=pdf.name,
                            pages=pdf.pages,
                            size_bytes=len(pdf.content),
                            storage_key=key,
                            revision=revision,
                            status="processing",
                            warnings=list(pdf.warnings),
                            chunk_count=0,
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(document)
                    else:
                        document.replacement_name = pdf.name
                        document.pending_revision = revision
                        document.pending_storage_key = key
                        document.replacement_error_code = None
                        document.replacement_error_message = None
                        document.updated_at = now
                    job = IndexJob(
                        document.id,
                        org_id,
                        revision,
                        key,
                        pdf.name,
                        pdf.pages,
                        len(pdf.content),
                        pdf.chunks,
                        pdf.warnings,
                        replace_id is not None,
                    )
                    db.commit()
                    stored = True
                summary = summarize_document(document)
                try:
                    future = self._executor.submit(self._index, job)
                except RuntimeError:
                    self._mark_failed(
                        job,
                        "processor_unavailable",
                        "Indexing could not start. Replace the PDF to retry.",
                    )
                    raise ApiError(
                        503,
                        "processing_busy",
                        "Indexing could not start. "
                        "The document is marked Failed; refresh the list.",
                    ) from None
                self._jobs[revision] = (job, future)
                submitted = True
                future.add_done_callback(lambda result: self._completed(job, result))
                return summary
        finally:
            if not submitted:
                self._slots.release()
            if key is not None and not stored:
                self.storage.discard(key)

    def _current(self, document: Document | None, job: IndexJob) -> bool:
        if document is None or document.org_id != job.org_id:
            return False
        if job.replacement:
            return document.pending_revision == job.revision
        return document.status == "processing" and document.revision == job.revision

    def _index(self, job: IndexJob) -> None:
        with self.database.session_factory() as db:
            if not self._current(db.get(Document, job.document_id), job):
                return
        vectors = normalize_embeddings(
            self.embedder.embed_documents([chunk.text for chunk in job.chunks]),
            len(job.chunks),
            self.embedder.dimensions,
        )
        with self._write() as db:
            document = db.get(Document, job.document_id)
            if not self._current(document, job):
                return
            if document is None:
                raise RuntimeError("The current document disappeared inside its write transaction.")
            old_key = document.storage_key if job.replacement else None
            with self.storage.reversible_remove([old_key]):
                db.execute(
                    delete(Chunk).where(
                        Chunk.org_id == job.org_id, Chunk.document_id == document.id
                    )
                )
                for source, vector in zip(job.chunks, vectors, strict=True):
                    db.add(
                        Chunk(
                            id=str(uuid4()),
                            org_id=job.org_id,
                            document_id=document.id,
                            ordinal=source.ordinal,
                            page=source.page,
                            text=source.text,
                            embedding=vector.astype("<f4").tobytes(),
                        )
                    )
                document.name = job.name
                document.pages = job.pages
                document.size_bytes = job.size_bytes
                document.storage_key = job.storage_key
                document.revision = job.revision
                document.status = "ready"
                document.error_code = None
                document.error_message = None
                document.warnings = list(job.warnings)
                document.chunk_count = len(job.chunks)
                document.embedding_model = self.embedder.model_name
                document.embedding_dimensions = int(vectors.shape[1])
                document.replacement_name = None
                document.pending_revision = None
                document.pending_storage_key = None
                document.replacement_error_code = None
                document.replacement_error_message = None
                document.updated_at = unix_time()
                db.commit()

    def _mark_failed(self, job: IndexJob, code: str, message: str) -> None:
        with self._write() as db:
            document = db.get(Document, job.document_id)
            if not self._current(document, job) or document is None:
                return
            if job.replacement:
                try:
                    self.storage.discard(job.storage_key)
                except StorageError:
                    logger.error("Replacement file cleanup failed document_id=%s", job.document_id)
                    message += (
                        " Temporary-file cleanup also failed; "
                        "delete or replace the document to retry cleanup."
                    )
                else:
                    document.pending_storage_key = None
                document.pending_revision = None
                document.replacement_error_code = code
                document.replacement_error_message = message + " The previous version was kept."
            else:
                document.status = "failed"
                document.error_code = code
                document.error_message = message
                document.chunk_count = 0
                db.execute(
                    delete(Chunk).where(
                        Chunk.org_id == job.org_id, Chunk.document_id == document.id
                    )
                )
            document.updated_at = unix_time()
            db.commit()

    def _completed(self, job: IndexJob, future: Future[None]) -> None:
        try:
            error = None if future.cancelled() else future.exception()
            if error is not None:
                logger.error(
                    "Document indexing failed document_id=%s error_type=%s",
                    job.document_id,
                    type(error).__name__,
                )
                code = "processing_failed"
                message = "The PDF could not be indexed. Replace the file to retry."
                if isinstance(error, StorageError):
                    code = "storage_unavailable"
                    message = "Private-file storage could not be updated."
                try:
                    self._mark_failed(job, code, message)
                except SQLAlchemyError:
                    logger.error(
                        "Failed index state could not be persisted document_id=%s", job.document_id
                    )
                    with self._lock:
                        self._failed_updates[job.revision] = (job, code, message)
        finally:
            with self._idle:
                self._jobs.pop(job.revision, None)
                self._slots.release()
                self._idle.notify_all()

    def delete_document(self, org_id: str, document_id: str) -> None:
        self._flush_failures()
        with self._write() as db:
            document = self._document(db, org_id, document_id)
            revisions = (document.revision, document.pending_revision)
            with self.storage.reversible_remove(
                [document.storage_key, document.pending_storage_key]
            ):
                db.delete(document)
                db.commit()
            for revision in revisions:
                if revision is not None and revision in self._jobs:
                    self._jobs[revision][1].cancel()

    def recover_interrupted(self) -> None:
        with self._write() as db:
            documents = db.scalars(
                select(Document).where(
                    (Document.status == "processing") | Document.pending_revision.is_not(None)
                )
            ).all()
            for document in documents:
                if document.pending_revision:
                    if document.pending_storage_key is not None:
                        try:
                            self.storage.discard(document.pending_storage_key)
                        except StorageError:
                            logger.error(
                                "Interrupted replacement cleanup failed document_id=%s", document.id
                            )
                        else:
                            document.pending_storage_key = None
                    document.pending_revision = None
                    document.replacement_error_code = "processing_interrupted"
                    document.replacement_error_message = (
                        "Replacement was interrupted by a server restart. "
                        "The previous version was kept."
                    )
                if document.status == "processing":
                    document.status = "failed"
                    document.error_code = "processing_interrupted"
                    document.error_message = (
                        "Indexing was interrupted by a server restart. Replace the PDF to retry."
                    )
                    document.chunk_count = 0
                    db.execute(
                        delete(Chunk).where(
                            Chunk.document_id == document.id, Chunk.org_id == document.org_id
                        )
                    )
                document.updated_at = unix_time()
                logger.warning(
                    "Interrupted document processing recovered document_id=%s", document.id
                )
            db.commit()

    def wait_until_idle(self, timeout: float = 10) -> bool:
        with self._idle:
            return self._idle.wait_for(lambda: not self._jobs, timeout=timeout)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)
