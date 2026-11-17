"""Almacenamiento de archivos (exportaciones PDF/Word/Excel, evidencias).

* Con credenciales `R2_*`: Cloudflare R2 (S3-compatible) vía boto3; descarga por URL prefirmada de vida corta.
* Sin credenciales: disco local (`STORAGE_DIR`, por defecto ``./storage``); descarga autenticada por el propio
  backend (el router verifica permisos y llama a `download_response`).

Uso desde un router/tarea::

    key = storage.build_key("exportaciones", "plan_12.pdf")
    storage.put(key, pdf_bytes, "application/pdf")
    ...
    return storage.download_response(key, "plan_12.pdf", "application/pdf")   # el router ya validó permisos
"""

from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Protocol

from fastapi import Response
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.errors import NotFound

logger = logging.getLogger("sti.storage")

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def build_key(prefix: str, filename: str) -> str:
    """Clave única y segura: ``<prefix>/<uuid>-<nombre_saneado>``."""
    name = _SAFE.sub("_", filename).strip("._") or "archivo"
    return f"{prefix.strip('/')}/{uuid.uuid4().hex[:12]}-{name}"


class Backend(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def presigned_url(self, key: str, filename: str | None = None, expires: int = 300) -> str | None: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("Ruta de almacenamiento no permitida.")
        return p

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise NotFound("El archivo ya no está disponible.", "ARCHIVO_NO_ENCONTRADO")
        return p.read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_file():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def presigned_url(self, key: str, filename: str | None = None, expires: int = 300) -> str | None:
        return None  # disco local: no hay URL prefirmada; descarga autenticada por el backend


class R2Storage:
    def __init__(self):
        import boto3
        from botocore.config import Config

        s = get_settings()
        self.bucket = s.r2_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.r2_endpoint_url,
            aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type or "application/octet-stream")

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            raise NotFound("El archivo ya no está disponible.", "ARCHIVO_NO_ENCONTRADO")

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def presigned_url(self, key: str, filename: str | None = None, expires: int = 300) -> str | None:
        params = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{_SAFE.sub("_", filename)}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)


_backend: Backend | None = None


def get_storage() -> Backend:
    global _backend
    if _backend is None:
        s = get_settings()
        if s.r2_configured:
            try:
                _backend = R2Storage()
                logger.info("Almacenamiento: Cloudflare R2 (%s)", s.r2_bucket)
            except Exception:
                logger.exception("No se pudo iniciar R2; se usa disco local")
        if _backend is None:
            _backend = LocalStorage(s.storage_dir)
            logger.info("Almacenamiento: disco local (%s)", s.storage_dir)
    return _backend


def reset_storage() -> None:
    global _backend
    _backend = None


# atajos
def put(key: str, data: bytes, content_type: str | None = None) -> None:
    get_storage().put(key, data, content_type)


def get(key: str) -> bytes:
    return get_storage().get(key)


def delete(key: str) -> None:
    get_storage().delete(key)


def exists(key: str) -> bool:
    return get_storage().exists(key)


def download_response(key: str, filename: str, content_type: str | None = None, *, inline: bool = False) -> Response:
    """Respuesta de descarga para un endpoint YA autenticado/autorizado.

    R2 -> redirección 302 a una URL prefirmada de 5 minutos; disco local -> bytes con Content-Disposition.
    """
    storage = get_storage()
    url = storage.presigned_url(key, filename)
    if url:
        return RedirectResponse(url, status_code=302)
    data = storage.get(key)
    ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    safe = _SAFE.sub("_", filename)
    disp = "inline" if inline else "attachment"
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'{disp}; filename="{safe}"',
                                                    "Cache-Control": "private, no-store"})
