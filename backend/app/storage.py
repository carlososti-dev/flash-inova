import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .config import get_settings


class Storage(Protocol):
    def save(self, folder: str, data: bytes, extension: str) -> str: ...
    def url(self, path: str | None) -> str | None: ...


class LocalStorage:
    """Desenvolvimento: arquivos numa pasta local, servidos em /files. Produção: Cloud Storage com a mesma interface."""

    def __init__(self, root: str):
        self.root = Path(root)

    def save(self, folder: str, data: bytes, extension: str) -> str:
        path = f"{folder}/{uuid.uuid4().hex}.{extension}"
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path

    def url(self, path: str | None) -> str | None:
        return f"/files/{path}" if path else None


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(get_settings().storage_dir)
