"""Crea (o restablece la contraseña de) la cuenta de Administrador del sistema.

    ADMIN_EMAIL=admin@unicordoba.edu.co ADMIN_PASSWORD='...' python -m scripts.create_admin
    python -m scripts.create_admin --email admin@... --password '...' [--nombre "Nombre Apellido"]

La arquitectura prevé UNA cuenta de administrador técnico, creada manualmente al desplegar.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.security import hash_password, validate_password_strength  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.enums import EstadoUsuario, Rol  # noqa: E402
from app.models.usuarios import Usuario  # noqa: E402
from app.services.accounts import create_user, normalize_email  # noqa: E402


def create_admin(db, email: str, password: str, nombre: str = "Administrador del sistema") -> tuple[Usuario, bool]:
    """Devuelve (usuario, creado). Si ya existe un usuario con ese correo, le restablece contraseña y lo activa."""
    email = normalize_email(email)
    validate_password_strength(password)
    user = db.scalar(select(Usuario).where(Usuario.email == email))
    if user is not None:
        if str(user.rol) != Rol.ADMIN:
            raise AppError(f"El correo {email} ya pertenece a una cuenta con rol {user.rol}; use otro correo.",
                           "EMAIL_DUPLICADO", status_code=409)
        user.password_hash = hash_password(password)
        user.password_changed_at = utcnow()
        user.estado = EstadoUsuario.ACTIVO
        user.failed_attempts = 0
        user.locked_until = None
        db.flush()
        return user, False
    user = create_user(db, email=email, nombre_completo=nombre, rol=Rol.ADMIN, password=password,
                       estado=EstadoUsuario.ACTIVO)
    return user, True


def main() -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default=s.admin_email or os.environ.get("ADMIN_EMAIL"))
    ap.add_argument("--password", default=s.admin_password or os.environ.get("ADMIN_PASSWORD"))
    ap.add_argument("--nombre", default="Administrador del sistema")
    args = ap.parse_args()
    if not args.email or not args.password:
        print("Falta ADMIN_EMAIL y/o ADMIN_PASSWORD (variables de entorno o argumentos --email/--password).",
              file=sys.stderr)
        return 2
    try:
        with session_scope() as db:
            otros = db.scalars(select(Usuario.email).where(Usuario.rol == Rol.ADMIN, Usuario.email != normalize_email(args.email))).all()
            if otros:
                print(f"Aviso: ya existen otros administradores: {', '.join(otros)}")
            user, creado = create_admin(db, args.email, args.password, args.nombre)
            print(("Administrador creado: " if creado else "Administrador actualizado: ") + user.email)
    except AppError as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
