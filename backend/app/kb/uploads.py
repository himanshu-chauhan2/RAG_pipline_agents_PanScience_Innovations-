from collections.abc import AsyncGenerator

from fastapi import Request
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from app.kb.limits import MAX_MULTIPART_BYTES, MAX_PDF_BYTES
from app.kb.pdf import file_error


async def read_pdf_upload(request: Request) -> tuple[str | None, bytes]:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "multipart/form-data"
    ):
        raise file_error("invalid_upload", "Send one PDF as the multipart field named 'file'.")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError:
            raise file_error("invalid_upload", "The request Content-Length is invalid.") from None
        if length < 0:
            raise file_error("invalid_upload", "The request Content-Length is invalid.")
        if length > MAX_MULTIPART_BYTES:
            raise file_error("file_too_large", "The PDF upload exceeds the 10 MB limit.", 413)
    body = bytearray()
    try:
        async for part in request.stream():
            if len(body) + len(part) > MAX_MULTIPART_BYTES:
                raise file_error("file_too_large", "The PDF upload exceeds the 10 MB limit.", 413)
            body.extend(part)
    except ClientDisconnect:
        raise file_error("upload_cancelled", "The upload connection was closed.", 499) from None

    async def stream() -> AsyncGenerator[bytes, None]:
        yield bytes(body)

    parser = MultiPartParser(
        request.headers, stream(), max_files=1, max_fields=0, max_part_size=MAX_MULTIPART_BYTES
    )
    try:
        form = await parser.parse()
    except (MultiPartException, MultipartParseError):
        raise file_error(
            "invalid_upload", "Send exactly one PDF in a field named 'file'."
        ) from None
    try:
        items = form.multi_items()
        if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
            raise file_error("invalid_upload", "Send exactly one PDF in a field named 'file'.")
        upload = items[0][1]
        content = await upload.read(MAX_PDF_BYTES + 1)
        if len(content) > MAX_PDF_BYTES:
            raise file_error(
                "file_too_large", "Each PDF must be at most 10,000,000 bytes (10 MB).", 413
            )
        return upload.filename, content
    finally:
        await form.close()
