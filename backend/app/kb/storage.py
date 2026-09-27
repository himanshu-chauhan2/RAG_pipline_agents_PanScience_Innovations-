import logging
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.kb.limits import MAX_PDF_BYTES

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


class PrivateStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}\.pdf", key) is None:
            raise StorageError("The stored document reference is invalid.")
        path = self.root / key
        if path.is_symlink():
            raise StorageError("A private document must not be a symbolic link.")
        return path

    def create(self, content: bytes) -> str:
        key = f"{uuid4().hex}.pdf"
        path = self.path(key)
        created = False
        try:
            with path.open("xb") as output:
                created = True
                output.write(content)
        except OSError as error:
            if created:
                self.discard(key)
            raise StorageError("The PDF could not be saved to private storage.") from error
        return key

    def discard(self, key: str) -> None:
        try:
            self.path(key).unlink()
        except FileNotFoundError:
            logger.warning("A private document file was already absent during cleanup.")
        except OSError as error:
            raise StorageError("A private document file could not be removed.") from error

    @contextmanager
    def reversible_remove(self, keys: Sequence[str | None]) -> Iterator[None]:
        backups: dict[str, bytes] = {}
        committed = False
        try:
            for key in dict.fromkeys(item for item in keys if item is not None):
                path = self.path(key)
                try:
                    with path.open("rb") as source:
                        content = source.read(MAX_PDF_BYTES + 1)
                except FileNotFoundError:
                    logger.warning("A private document file was already absent during removal.")
                    continue
                except OSError as error:
                    raise StorageError(
                        "A private document file could not be read for removal."
                    ) from error
                if len(content) > MAX_PDF_BYTES:
                    raise StorageError("A stored PDF exceeds the supported size limit.")
                backups[key] = content
                self.discard(key)
            yield
            committed = True
        finally:
            if not committed:
                for key, content in backups.items():
                    path = self.path(key)
                    if not path.exists():
                        try:
                            path.write_bytes(content)
                        except OSError as error:
                            logger.error(
                                "Private document rollback failed; operator action is required."
                            )
                            raise StorageError("Private document rollback failed.") from error
