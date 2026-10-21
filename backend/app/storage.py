import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .config import get_settings


# Assinaturas dos formatos de imagem aceitos (SVG fica de fora: pode carregar script).
IMAGE_FORMATS = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"RIFF": "webp"}


def image_extension(data: bytes) -> str | None:
    """Extensão pelo conteúdo do arquivo (não pelo nome): png, jpg, webp ou None."""
    extension = next((ext for magic, ext in IMAGE_FORMATS.items() if data.startswith(magic)), None)
    if extension == "webp" and data[8:12] != b"WEBP":
        return None
    return extension


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
