"""Agrega todos los routers de /api/v1. Los slices NO editan este archivo: cada modulo ya esta incluido.

Para agregar un modulo nuevo: crear `app/api/v1/<modulo>.py` con `router = APIRouter(prefix=..., tags=[...])`,
importarlo aqui y hacer `api_router.include_router(<modulo>.router)` (cambio de una linea + una de import).
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    aq10,
    auth,
    calendario,
    caracterizacion,
    catalogo_dua,
    consentimiento,
    contexto_barreras,
    docente,
    estudiantes,
    evaluacion,
    exportaciones,
    familiar,
    health,
    negociacion,
    notificaciones,
    planes,
    reportes,
    seguimiento,
    solicitudes,
    sugerencias,
    trayectoria,
    usuarios,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(usuarios.router)
api_router.include_router(catalogo_dua.router)
api_router.include_router(calendario.router)
api_router.include_router(notificaciones.router)
api_router.include_router(reportes.router)
api_router.include_router(solicitudes.router)
api_router.include_router(consentimiento.router)
api_router.include_router(aq10.router)
api_router.include_router(caracterizacion.router)
api_router.include_router(contexto_barreras.router)
api_router.include_router(sugerencias.router)
api_router.include_router(planes.router)
api_router.include_router(negociacion.router)
api_router.include_router(exportaciones.router)
api_router.include_router(seguimiento.router)
api_router.include_router(evaluacion.router)
api_router.include_router(trayectoria.router)
api_router.include_router(docente.router)
api_router.include_router(familiar.router)
api_router.include_router(estudiantes.router)
