"""Configuración central (pydantic-settings). Lee variables de entorno y `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # .../backend


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # --- Aplicación ---
    app_name: str = "STI - Sistema Tutor Inteligente"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:5173"
    public_api_url: str = "http://localhost:8000"
    activation_path: str = "/activar"  # ruta del frontend: {FRONTEND_URL}{activation_path}?token=...
    reset_path: str = "/restablecer"  # ruta del frontend: {FRONTEND_URL}{reset_path}?token=...

    # --- Base de datos ---
    database_url: str = f"sqlite:///{(BASE_DIR / 'sti_dev.db').as_posix()}"
    db_echo: bool = False

    # --- Seguridad ---
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480  # 8 h (RNF-06)
    refresh_token_days: int = 14
    refresh_cookie_name: str = "sti_refresh"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    data_encryption_key: str = ""  # base64 de 32 bytes (AES-256)
    max_login_attempts: int = 5
    lockout_minutes: int = 15
    activation_token_hours: int = 72
    reset_token_hours: int = 2
    min_password_length: int = 10
    login_rate_limit_per_minute: int = 20  # por IP; 0 desactiva
    hsts_enabled: bool | None = None  # None = solo en producción o con cookie_secure

    # --- Registro autónomo (sin verificación por correo) ---
    # Los correos NO se verifican: el registro es inmediato y la recuperación de contraseña usa un código de
    # recuperación que se muestra una sola vez. Poner EMAIL_ACTIVATION_REQUIRED=true (con SMTP) vuelve al flujo
    # de invitación por enlace para las cuentas que crea el personal.
    registro_abierto: bool = True
    staff_access_code: str = ""  # código para registrarse como BIENESTAR/COORDINADOR; vacío = solo lo crea el admin
    email_activation_required: bool = False
    registro_rate_limit_per_hour: int = 30  # por IP; 0 desactiva

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Alcance de bienestar ---
    bienestar_scope: Literal["all", "assigned"] = "all"

    # --- Correo ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "sti@unicordoba.edu.co"
    smtp_starttls: bool = True
    smtp_ssl: bool = False

    # --- Tareas asíncronas ---
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    jobs_secret: str = ""

    # --- Almacenamiento (Cloudflare R2 / disco local) ---
    storage_dir: str = str(BASE_DIR / "storage")
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    # --- Observabilidad ---
    sentry_dsn: str = ""

    # --- IA (opcional) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- SSO OIDC genérico ---
    sso_enabled: bool = False
    sso_issuer: str = ""
    sso_client_id: str = ""
    sso_client_secret: str = ""
    sso_redirect_uri: str = ""
    sso_scopes: str = "openid email profile"
    sso_authorization_endpoint: str = ""
    sso_token_endpoint: str = ""
    sso_userinfo_endpoint: str = ""

    # --- Semilla / admin ---
    seed_demo: bool = False
    admin_email: str = ""
    admin_password: str = ""

    @field_validator("cookie_samesite", mode="before")
    @classmethod
    def _lower_samesite(cls, v):
        return v.lower() if isinstance(v, str) else v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)

    @property
    def r2_configured(self) -> bool:
        return bool(self.r2_endpoint_url and self.r2_access_key_id and self.r2_secret_access_key and self.r2_bucket)

    @property
    def sso_configured(self) -> bool:
        return bool(
            self.sso_enabled
            and self.sso_client_id
            and self.sso_client_secret
            and self.sso_redirect_uri
            and (self.sso_issuer or (self.sso_authorization_endpoint and self.sso_token_endpoint))
        )

    @property
    def effective_database_url(self) -> str:
        """Normaliza URLs de Render (`postgres://`) al driver psycopg 3."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
