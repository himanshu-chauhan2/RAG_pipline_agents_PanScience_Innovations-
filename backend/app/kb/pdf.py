import logging
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.errors import ApiError
from app.kb.limits import CHUNK_CHARACTERS, CHUNK_OVERLAP, MAX_PDF_BYTES, MAX_PDF_PAGES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageChunk:
    page: int
    ordinal: int
    text: str


@dataclass(frozen=True)
class PreparedPdf:
    name: str
    content: bytes
    pages: int
    chunks: tuple[PageChunk, ...]
    warnings: tuple[str, ...]


def file_error(code: str, message: str, status: int = 400) -> ApiError:
    return ApiError(status, code, message, {"file": message})


def normalize_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 255 or any(ord(character) < 32 for character in name):
        raise file_error("invalid_filename", "Use a PDF filename between 1 and 255 characters.")
    if not name.lower().endswith(".pdf"):
        raise file_error("invalid_pdf", "Only PDF files are supported.")
    return name


def split_page(text: str) -> list[str]:
    text = " ".join(text.split())
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARACTERS, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_CHARACTERS // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        next_start = max(start + 1, end - CHUNK_OVERLAP)
        while next_start < end and text[next_start - 1] != " ":
            next_start += 1
        start = next_start
    return chunks


def prepare_pdf(filename: str | None, content: bytes) -> PreparedPdf:
    name = normalize_filename(filename)
    if len(content) > MAX_PDF_BYTES:
        raise file_error(
            "file_too_large", "Each PDF must be at most 10,000,000 bytes (10 MB).", 413
        )
    if not content.startswith(b"%PDF-"):
        raise file_error("invalid_pdf", "This file is not a readable PDF.")
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise file_error(
                "encrypted_pdf", "Password-protected or encrypted PDFs are not supported."
            )
        pages = len(reader.pages)
        if pages > MAX_PDF_PAGES:
            raise file_error("page_limit", "Each PDF may contain at most 20 pages.")
        if pages == 0:
            raise file_error("invalid_pdf", "The PDF contains no pages.")
        chunks: list[PageChunk] = []
        skipped: list[int] = []
        for page_number, page in enumerate(reader.pages, 1):
            parts = split_page(page.extract_text())
            if not parts:
                skipped.append(page_number)
            for text in parts:
                chunks.append(PageChunk(page=page_number, ordinal=len(chunks), text=text))
    except (PyPdfError, ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        logger.warning("PDF parsing failed error_type=%s", type(error).__name__)
        raise file_error(
            "invalid_pdf", "The PDF could not be read. Upload a valid text-based PDF."
        ) from None
    if not chunks:
        raise file_error(
            "no_readable_text",
            "The PDF has no extractable text. Scanned images require OCR, which is not available.",
        )
    warnings = (
        (
            f"No text could be extracted from pages {', '.join(map(str, skipped))}; "
            "those pages are not indexed. OCR is not available.",
        )
        if skipped
        else ()
    )
    return PreparedPdf(name, content, pages, tuple(chunks), warnings)
