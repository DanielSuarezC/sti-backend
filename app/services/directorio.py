"""Directorio institucional (Vía 2, RF-04): verifica código estudiantil y correo institucional.

`DirectorioInstitucional` es el adaptador (p. ej. SSO/LDAP/SIGAA en el futuro). La implementación por defecto
(`DirectorioPorDefecto`) valida el dominio del correo contra `INSTITUTIONAL_EMAIL_DOMAINS` y, si ya existe un
estudiante/matrícula con ese código, compara el correo registrado.

`INSTITUTIONAL_EMAIL_DOMAINS` (variable de entorno, separada por comas; `*` = cualquier dominio):
  * sin definir en producción  -> `unicordoba.edu.co`
  * sin definir en desarrollo/pruebas -> `*` (cualquier dominio)
`SOLICITUDES_RATE_LIMIT_PER_HOUR` (por defecto 5; 0 desactiva) limita el formulario público por IP.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, get_settings
from app.models.usuarios import Estudiante, Usuario

DOMINIO_POR_DEFECTO = "unicordoba.edu.co"


class DirectorySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )
    institutional_email_domains: str = ""
    solicitudes_rate_limit_per_hour: int = 5


@lru_cache
def directory_settings() -> DirectorySettings:
    return DirectorySettings()


def reset_directory_settings() -> None:
    directory_settings.cache_clear()


def dominios_permitidos() -> list[str]:
    raw = directory_settings().institutional_email_domains.strip()
    if not raw:
        return ["*"] if not get_settings().is_production else [DOMINIO_POR_DEFECTO]
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


def email_dominio_permitido(email: str) -> bool:
    doms = dominios_permitidos()
    if "*" in doms:
        return True
    dominio = email.strip().lower().rsplit("@", 1)[-1]
    return any(dominio == d or dominio.endswith("." + d) for d in doms)


def mensaje_dominio() -> str:
    doms = [d for d in dominios_permitidos() if d != "*"]
    return "Use su correo institucional" + (f" (termina en @{doms[0]})" if doms else "") + "."


@dataclass
class ResultadoDirectorio:
    dominio_ok: bool
    #: True = el directorio confirma código y correo; False = hay dato en el directorio pero no coincide;
    #: None = no se pudo verificar (no hay registro previo con ese código).
    valido: bool | None = None
    programa_id: int | None = None
    nombre: str | None = None


class DirectorioInstitucional(Protocol):
    def verificar(self, db: Session, codigo: str, email: str) -> ResultadoDirectorio: ...


class DirectorioPorDefecto:
    def verificar(self, db: Session, codigo: str, email: str) -> ResultadoDirectorio:
        dominio_ok = email_dominio_permitido(email)
        est = db.scalar(
            select(Estudiante).where(Estudiante.codigo_estudiante == codigo).execution_options(include_deleted=True)
        )
        if est is None:
            return ResultadoDirectorio(dominio_ok=dominio_ok, valido=None)
        usuario = db.get(Usuario, est.usuario_id)
        coincide = bool(usuario and usuario.email.lower() == email.strip().lower())
        return ResultadoDirectorio(
            dominio_ok=dominio_ok, valido=coincide, programa_id=est.programa_id,
            nombre=usuario.nombre_completo if usuario else None,
        )


_directorio: DirectorioInstitucional = DirectorioPorDefecto()


def get_directorio() -> DirectorioInstitucional:
    return _directorio


def set_directorio(directorio: DirectorioInstitucional) -> None:
    """Permite conectar un directorio real (SSO/SIGAA) o un doble de prueba."""
    global _directorio
    _directorio = directorio
