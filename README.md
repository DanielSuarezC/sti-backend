# STI — Backend (FastAPI)

API del Sistema Tutor Inteligente (Plan MAAR-TEA). Python 3.11 en producción; corre también en 3.12–3.14 local.
SQLite en desarrollo y pruebas; PostgreSQL 16 en producción (nada específico de SQLite en el código de negocio).

Documentos: `docs/MODELO.md` (100 tablas, reconciliación con el ERD), `docs/api/auth.md` (contrato de autenticación),
`docs/api/<slice>.md` (los llena cada slice), `../BUILD_SPEC.md` (especificación funcional).

## Arranque local en Windows (PowerShell)

```powershell
cd sti\backend
py -3.14 -m venv .venv            # o py -3.11
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt          # (+ requirements-ai.txt opcional para IA)
copy .env.example .env                       # opcional: en desarrollo todo tiene valores por defecto
alembic upgrade head                         # crea sti_dev.db con las 100 tablas
$env:SEED_DEMO="1"; python -m scripts.seed   # referencia + usuarios demo (omitir SEED_DEMO=1 para solo referencia)
uvicorn app.main:app --reload                # http://localhost:8000/docs
```

* Sin `.env`: `JWT_SECRET` y `DATA_ENCRYPTION_KEY` se generan una vez y se guardan en `.dev_secrets.json` (ignorado por git).
  **En producción faltan = el servidor no arranca** (error claro). Respalde `DATA_ENCRYPTION_KEY`: sin ella no se descifran AQ-10, F1 ni notas F10.
* Admin real: `$env:ADMIN_EMAIL="..."; $env:ADMIN_PASSWORD="..."; python -m scripts.create_admin`
* Usuarios demo (`SEED_DEMO=1`, contraseña `Demo-STI-2026!` o `DEMO_PASSWORD`): `bienestar.demo@sti-demo.example.com`, `coordinador.demo@…`,
  `docente.demo@…`, `familiar.demo@…`, `est1.demo@…` … `est5.demo@…` (etapas: invitado, sin F0, F0, caracterización, plan en implementación).
  **Cámbiela o no cargue la demo en producción.** No hay admin demo.
* Salud: `GET /health` y `GET /api/v1/health`.

## Pruebas y calidad

```powershell
pytest                       # SQLite en memoria; 70 pruebas
pytest --cov=app --cov-report=term-missing
ruff check app tests scripts
```

## Variables de entorno

Lista completa y comentada en `.env.example`. Las críticas: `APP_ENV`, `DATABASE_URL`, `JWT_SECRET`, `DATA_ENCRYPTION_KEY`, `COOKIE_SECURE`,
`COOKIE_SAMESITE`, `CORS_ORIGINS`, `FRONTEND_URL`, `SMTP_*`, `CELERY_BROKER_URL`, `JOBS_SECRET`, `R2_*`, `SENTRY_DSN`, `OPENAI_API_KEY`, `SSO_*`.
Degradaciones: sin SMTP → correos en `email_outbox` (OMITIDO) + logs; sin broker → tareas en línea/hilo; sin R2 → `./storage`; sin SSO → 501; sin OpenAI → plantillas.

## Estructura

```
app/
  main.py                 FastAPI, lifespan (valida claves), CORS, Sentry, handlers
  core/                   config, db, security, crypto, deps, permissions, audit, errors, pagination, ratelimit, middleware
  models/                 100 tablas (ver docs/MODELO.md); enums.py = enums del dominio
  schemas/                Pydantic v2 (common, auth); los slices agregan los suyos
  api/v1/                 router.py (incluye TODO) + un archivo por módulo (stubs con `# OWNER: slice X`)
  services/               notifications, tasks, email, storage, accounts, params, plan_states, jobs, sso
  workers/celery_app.py   Celery (solo con CELERY_BROKER_URL)
  data/                   AQ-10 (Allison 2012, es) y catálogo DUA CAST 2.2 (semilla)
alembic/                  migración inicial 0001 (válida en SQLite y PostgreSQL)
scripts/                  seed.py, create_admin.py, gen_modelo_doc.py
tests/                    conftest + fábricas (build_world) + pruebas de auth, cifrado, auditoría, RBAC, consentimiento...
```

## Cómo agregar un router nuevo

1. Los módulos acordados ya existen como stubs en `app/api/v1/<modulo>.py` y ya están incluidos en `router.py` (no lo toque):
   solo complete `router = APIRouter(prefix=..., tags=[...])`.
2. Para un módulo nuevo: cree `app/api/v1/<modulo>.py`, agregue `from app.api.v1 import <modulo>` y `api_router.include_router(<modulo>.router)` en `router.py`.
3. Patrón de endpoint:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core import audit
from app.core.deps import Accion, Recurso, assert_can, get_db, require_roles_consent
from app.core.errors import NotFound
from app.models.enums import Rol

router = APIRouter(prefix="/ejemplo", tags=["ejemplo"])

@router.get("/estudiantes/{estudiante_id}/aq10")
def ver(estudiante_id: int, request: Request, db: Session = Depends(get_db),
        user=Depends(require_roles_consent(Rol.BIENESTAR, Rol.ESTUDIANTE))):
    assert_can(db, user, estudiante_id, Recurso.AQ10, Accion.LEER)     # alcance + matriz §12.1 + F0
    audit.log(db, user, audit.Accion.ACCESO_AQ10, "respuesta_aq10", None, estudiante_id=estudiante_id, request=request)
    db.commit()                                                          # el router decide el commit
    ...
```

4. Documente cada endpoint en `docs/api/<modulo>.md` y agregue pruebas en `tests/` (use `build_world`, `auth_headers`).

## Helpers para los slices (firmas)

| Módulo | Qué ofrece |
|---|---|
| `core.deps` | `get_db`, `get_current_user`, `get_active_user`, `require_roles(*roles)`, `require_consent`, `require_roles_consent(*roles)`; re-exporta todo `permissions` |
| `core.permissions` | `Recurso`, `Accion`, `MATRIZ`; `can(db,user,est_id,recurso,accion=LEER)`, `assert_can(db,user,est_id,recurso,accion,*,require_consent=True)->Estudiante`, `can_access_student`, `can_view_clinical`, `can_view_aq10`, `can_view_plan`, `can_write`, `students_scope_criterion(user)` / `students_scope_criterion_db(db,user)` (para listados), `docente_ajuste_ids(db,user,plan_id)`, `student_has_consent`, `get_estudiante_or_404`, `get_own_estudiante`, `coordinador_programa_ids` |
| `core.audit` | `log(db, actor, accion, entidad, entidad_id=None, detalle=None, *, request=None, estudiante_id=None, commit=False)`, `Accion` (catálogo) |
| `core.errors` | `AppError(detail, code)`, `BadRequest`, `Unauthorized`, `Forbidden`, `NotFound`, `Conflict`, `Unprocessable`, `ConsentRequired` |
| `core.pagination` | `PageParams` (dependencia), `paginate(db, stmt, params, transform=None)` → `{items,total,page,page_size}`, `Page[T]` |
| `core.crypto` | tipos `EncryptedText/EncryptedJSON/EncryptedDate`; alias `CTXT`, `CJSON`, `CDATE` en `models.base` |
| `models.base` | `Entity` (id+timestamps+soft delete), `.soft_delete(actor_id, reason)`, `.restore()`, `fk()`, `enum_col()`, `unique_active()`; `select(...).execution_options(include_deleted=True)` |
| `services.notifications` | `notify(db, Evento.X, destinatarios, payload, canales=None, *, dedupe_key=None)`, `Evento`, `CATALOGO`, `get_notification_user_ids` |
| `services.tasks` | `@task("nombre")`, `enqueue(fn, *args)` (Celery / en línea / hilo) |
| `services.storage` | `build_key(prefix, filename)`, `put/get/delete/exists`, `download_response(key, filename, content_type)` |
| `services.accounts` | `create_user(db, ...)`, `invite_user(db, user, actor=, request=)` (token 72 h + correo) |
| `services.params` | `get_param(db, clave)`, `set_param`, `ensure_defaults` (`aq10_punto_corte`, `umbral_inasistencia`, `max_ciclos_negociacion`...) |
| `services.plan_states` | `TRANSICIONES`, `can_transition`, `assert_transition(origen, destino)` |
| `services.jobs` | `run_daily_jobs()`, lista `JOBS` (el slice A completa los stubs `# TODO(slice A)`) |

Reglas transversales: errores en español `{detail, code}`; ningún `DELETE` físico (use `soft_delete`); registrar en auditoría el acceso a AQ-10/F1,
firmas, cambios de semáforo, exportaciones y consentimiento; el puntaje AQ-10, el diagnóstico y los nombres **nunca** salen hacia IA (`services/ai_gateway.py`, slice B).

## Docker / Render

`Dockerfile` (python:3.11-slim + libs WeasyPrint, usuario no root, `alembic upgrade head` + `uvicorn --port $PORT`). Worker opcional:
`celery -A app.workers.celery_app.celery_app worker -l info` y `beat`. Sin worker: cron externo contra `POST /api/v1/admin/jobs/run-daily` (`X-Jobs-Secret`).
