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


# Anexos das ideias: PDF, imagens e documentos do Office (que são arquivos ZIP por dentro).
OFFICE_EXTENSIONS = {"docx", "xlsx", "pptx"}
ATTACHMENT_TYPES = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def attachment_extension(data: bytes, filename: str) -> str | None:
    """Extensão de um anexo conferida pelo conteúdo; None se o formato não for aceito."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if (image := image_extension(data)) is not None:
        return image
    name_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if data.startswith(b"PK\x03\x04") and name_ext in OFFICE_EXTENSIONS:
        return name_ext
    return None


class Storage(Protocol):
    def save(self, folder: str, data: bytes, extension: str) -> str: ...
    def url(self, path: str | None) -> str | None: ...
    def read(self, path: str) -> bytes | None: ...


class LocalStorage:
    """Desenvolvimento: arquivos numa pasta local, servidos em /files."""

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

    def read(self, path: str) -> bytes | None:
        root = self.root.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return None
        return target.read_bytes()


class CloudStorage:
    """Produção: um bucket privado do Google Cloud Storage (o app lê e entrega; nada fica público no bucket)."""

    def __init__(self, bucket: str, prefix: str):
        from google.cloud import storage  # importado só em produção

        self.bucket = storage.Client().bucket(bucket)
        self.prefix = prefix

    def save(self, folder: str, data: bytes, extension: str) -> str:
        path = f"{folder}/{uuid.uuid4().hex}.{extension}"
        self.bucket.blob(f"{self.prefix}/{path}").upload_from_string(data)
        return path

    def url(self, path: str | None) -> str | None:
        return f"/files/{path}" if path else None

    def read(self, path: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        if ".." in path.split("/"):
            return None
        try:
            return self.bucket.blob(f"{self.prefix}/{path}").download_as_bytes()
        except NotFound:
            return None


def _make(local_dir: str, prefix: str) -> Storage:
    s = get_settings()
    if s.storage_backend == "gcs":
        return CloudStorage(s.gcs_bucket, prefix)
    return LocalStorage(local_dir)


@lru_cache
def get_storage() -> Storage:
    return _make(get_settings().storage_dir, "public")


@lru_cache
def get_private_storage() -> Storage:
    return _make(get_settings().private_storage_dir, "private")
