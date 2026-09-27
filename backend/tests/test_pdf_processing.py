from io import BytesIO

import numpy as np
import pytest
from conftest import make_pdf, pad_pdf
from pypdf import PdfReader, PdfWriter

from app.errors import ApiError
from app.kb.embeddings import normalize_embeddings
from app.kb.limits import CHUNK_CHARACTERS, MAX_PDF_BYTES
from app.kb.pdf import prepare_pdf, split_page


def test_page_provenance_and_display_name() -> None:
    pdf = prepare_pdf(r"C:\fakepath\Policy.PDF", make_pdf(pages=3))
    assert pdf.name == "Policy.PDF"
    assert pdf.pages == 3
    assert [chunk.page for chunk in pdf.chunks] == [1, 2, 3]
    assert [chunk.ordinal for chunk in pdf.chunks] == [0, 1, 2]
    for chunk in pdf.chunks:
        assert f"Page {chunk.page}:" in chunk.text


def test_chunk_size_overlap_and_full_word_coverage() -> None:
    words = [f"word{number:04d}" for number in range(600)]
    chunks = split_page(" ".join(words))
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= CHUNK_CHARACTERS for chunk in chunks)
    assert set(words) == {word for chunk in chunks for word in chunk.split()}
    for left, right in zip(chunks, chunks[1:], strict=False):
        assert set(left.split()) & set(right.split())


def test_long_unbroken_text_does_not_loop_or_disappear() -> None:
    text = "x" * 2401
    chunks = split_page(text)
    assert "".join(chunks) == text
    assert max(map(len, chunks)) <= CHUNK_CHARACTERS


@pytest.mark.parametrize("pages,allowed", [(20, True), (21, False)])
def test_exact_page_limit(pages: int, allowed: bool) -> None:
    content = make_pdf(pages=pages)
    if allowed:
        assert prepare_pdf("policy.pdf", content).pages == 20
    else:
        with pytest.raises(ApiError) as error:
            prepare_pdf("policy.pdf", content)
        assert error.value.code == "page_limit"


def test_exact_decimal_megabyte_limit() -> None:
    content = pad_pdf(make_pdf(), MAX_PDF_BYTES)
    assert len(prepare_pdf("limit.pdf", content).content) == 10_000_000
    with pytest.raises(ApiError) as error:
        prepare_pdf("limit.pdf", content + b" ")
    assert error.value.status == 413
    assert error.value.code == "file_too_large"


@pytest.mark.parametrize(
    "filename,content,code",
    [
        ("policy.txt", make_pdf(), "invalid_pdf"),
        ("policy.pdf", b"not a PDF", "invalid_pdf"),
        ("policy.pdf", b"%PDF-1.7\nbroken", "invalid_pdf"),
        ("policy.pdf", b"", "invalid_pdf"),
        ("bad\nname.pdf", make_pdf(), "invalid_filename"),
        ("policy.pdf", make_pdf(text=""), "no_readable_text"),
    ],
)
def test_unsupported_inputs_are_explicit_errors(filename: str, content: bytes, code: str) -> None:
    with pytest.raises(ApiError) as error:
        prepare_pdf(filename, content)
    assert error.value.code == code
    assert "file" in (error.value.fields or {})


def test_encrypted_pdf_is_rejected_without_decryption() -> None:
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(make_pdf())))
    writer.encrypt("test-only-password")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ApiError) as error:
        prepare_pdf("encrypted.pdf", output.getvalue())
    assert error.value.code == "encrypted_pdf"


def test_blank_pages_keep_original_page_numbers_and_produce_warnings() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.append(PdfReader(BytesIO(make_pdf("Second physical page policy"))))
    output = BytesIO()
    writer.write(output)
    pdf = prepare_pdf("mixed.pdf", output.getvalue())
    assert pdf.pages == 2
    assert [chunk.page for chunk in pdf.chunks] == [2]
    assert len(pdf.warnings) == 1 and "pages 1" in pdf.warnings[0]


@pytest.mark.parametrize(
    "matrix,count",
    [
        (np.array([[0, 0]], dtype=np.float32), 1),
        (np.array([[np.nan, 1]], dtype=np.float32), 1),
        (np.array([[np.inf, 1]], dtype=np.float32), 1),
        (np.array([[1, 1]], dtype=np.float32), 2),
        (np.empty((0, 4), dtype=np.float32), 0),
        (np.array([1, 2], dtype=np.float32), 1),
    ],
)
def test_bad_embeddings_are_rejected(matrix, count: int) -> None:
    with pytest.raises(ValueError):
        normalize_embeddings(matrix, count, 2)


def test_embeddings_are_normalized_and_preserve_dimensions() -> None:
    result = normalize_embeddings(np.array([[3, 4], [1, 1]], dtype=np.float32), 2, 2)
    assert result.shape == (2, 2) and result.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(result, axis=1), [1, 1], atol=1e-6)
