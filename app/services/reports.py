"""Reportes institucionales agregados (M9, RF-36, HU-26/27) y exportación PDF/Excel.

PRIVACIDAD: solo datos agregados, sin identificadores. Toda celda con 0 < n < k (k = `reportes_k_minimo`, nunca
menor que 3) se suprime: se devuelve `null`. En distribuciones que son una partición (las celdas suman el total) se
aplica además supresión complementaria para que no pueda recuperarse una celda restando. Los conteos de personas
son de estudiantes DISTINTOS. El Coordinador solo ve sus programas (`coordinador_programa_ids`); el Admin, todos.
"""

from __future__ import annotations

import html
import io
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden
from app.core.permissions import coordinador_programa_ids
from app.models.academico import ProgramaAcademico
from app.models.base import utcnow
from app.models.dua import CasoCbr, EstrategiaDuaCatalogo
from app.models.enums import EstadoPlanEnum, Rol
from app.models.mapa import BarreraIdentificada
from app.models.plan import (
    AjusteRazonable,
    EstrategiaDua,
    PlanMaarTea,
    RespuestaAmbiente,
    RespuestaComunicacion,
    RespuestaEvaluacion,
    RespuestaInteraccion,
    RespuestaPedagogia,
    RespuestaTecnologia,
)
from app.models.sistema import EmailOutbox, Exportacion, LogAuditoria, Notificacion
from app.models.trayectoria import Graduacion, Permanencia, Progresion, TrayectoriaAcademica
from app.models.usuarios import Estudiante, Usuario
from app.services import params
from app.services.system_params import k_minimo

logger = logging.getLogger("sti.reports")

PLANES_ACTIVOS = (EstadoPlanEnum.APROBADO, EstadoPlanEnum.IMPLEMENTACION, EstadoPlanEnum.SEGUIMIENTO)
TIPOS = ("dashboard", "trayectorias", "ajustes-frecuentes", "efectividad-dua", "uso")
NOTA_SUPRESION = "Las celdas con menos de {k} personas se ocultan (aparecen vacías) para proteger la privacidad."


class Supresor:
    def __init__(self, k: int):
        self.k = k
        self.suprimidas = 0

    def cell(self, n: int | None) -> int | None:
        if n is None:
            return None
        if 0 < n < self.k:
            self.suprimidas += 1
            return None
        return n

    def total(self, n: int) -> int | None:
        return self.cell(n)

    def distribucion(self, conteos: dict[str, int], *, particion: bool = True) -> dict[str, int | None]:
        total = sum(conteos.values()) if particion else None
        ocultas = {c for c, n in conteos.items() if 0 < n < self.k}
        if particion and ocultas:
            if total is not None and total < self.k:
                ocultas = {c for c, n in conteos.items() if n > 0}
            else:
                while sum(conteos[c] for c in ocultas) < self.k:
                    candidatos = sorted((c for c, n in conteos.items() if n > 0 and c not in ocultas), key=lambda c: conteos[c])
                    if not candidatos:
                        break
                    ocultas.add(candidatos[0])
        out: dict[str, int | None] = {}
        for c, n in conteos.items():
            if c in ocultas:
                out[c] = None
                self.suprimidas += 1
            else:
                out[c] = n
        return out


# ----------------------------------------------------------------------------- alcance
def resolve_scope(db: Session, user: Usuario, programa_id: int | None) -> list[ProgramaAcademico]:
    if str(user.rol) == Rol.ADMIN:
        propios = None
    elif str(user.rol) == Rol.COORDINADOR:
        propios = coordinador_programa_ids(db, user)
    else:
        raise Forbidden("Su rol no tiene acceso a los reportes institucionales.", "ROL_NO_PERMITIDO")
    if programa_id is not None and propios is not None and programa_id not in propios:
        raise Forbidden("Ese programa no está dentro de su alcance como coordinador.", "PROGRAMA_FUERA_DE_ALCANCE")
    stmt = select(ProgramaAcademico).order_by(ProgramaAcademico.nombre_programa)
    if programa_id is not None:
        stmt = stmt.where(ProgramaAcademico.id == programa_id)
    elif propios is not None:
        stmt = stmt.where(ProgramaAcademico.id.in_(propios or [-1]))
    return list(db.scalars(stmt))


def _planes_activos(db: Session, prog_ids: list[int], semestre: str | None):
    stmt = (
        select(PlanMaarTea.id, PlanMaarTea.estudiante_id, PlanMaarTea.semaforo_actual, Estudiante.programa_id)
        .join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id)
        .where(PlanMaarTea.estado.in_(PLANES_ACTIVOS), Estudiante.programa_id.in_(prog_ids or [-1]))
    )
    if semestre:
        stmt = stmt.where(PlanMaarTea.semestre_academico == semestre)
    return db.execute(stmt).all()


def _latest_trayectoria(db: Session, est_ids: set[int]) -> dict[int, TrayectoriaAcademica]:
    out: dict[int, TrayectoriaAcademica] = {}
    if not est_ids:
        return out
    for t in db.scalars(select(TrayectoriaAcademica).where(TrayectoriaAcademica.estudiante_id.in_(est_ids))
                        .order_by(TrayectoriaAcademica.fecha_inicio_semestre)):
        out[t.estudiante_id] = t  # el último (más reciente) sobrescribe
    return out


def _cabecera(user: Usuario, progs: list[ProgramaAcademico], k: int, **filtros) -> dict[str, Any]:
    return {
        "k_minimo": k, "generado_at": utcnow().isoformat(),
        "alcance": {"rol": str(user.rol), "programas": [{"id": p.id, "nombre": p.nombre_programa} for p in progs]},
        "filtros": filtros, "nota_privacidad": NOTA_SUPRESION.format(k=k),
    }


# ----------------------------------------------------------------------------- dashboard
def dashboard(db: Session, user: Usuario, programa_id: int | None = None, semestre: str | None = None) -> dict[str, Any]:
    progs = resolve_scope(db, user, programa_id)
    k = k_minimo(db)
    sup = Supresor(k)
    ids = [p.id for p in progs]
    planes = _planes_activos(db, ids, semestre)
    est_por_prog: dict[int, set[int]] = defaultdict(set)
    sem_por_prog: dict[int, dict[str, int]] = defaultdict(lambda: {"VERDE": 0, "AMARILLO": 0, "ROJO": 0, "SIN_REGISTRO": 0})
    for _pid, est_id, semaforo, prog in planes:
        if est_id in est_por_prog[prog]:
            continue
        est_por_prog[prog].add(est_id)
        sem_por_prog[prog][str(semaforo) if semaforo else "SIN_REGISTRO"] += 1
    all_est = set().union(*est_por_prog.values()) if est_por_prog else set()
    barreras: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    if all_est:
        for est_id, tipo in db.execute(select(BarreraIdentificada.estudiante_id, BarreraIdentificada.tipo_barrera)
                                       .where(BarreraIdentificada.estudiante_id.in_(all_est))).all():
            barreras[est_id][str(tipo)].add(est_id)
    trayect = _latest_trayectoria(db, all_est)
    perm = {}
    if trayect:
        for t_id, cont in db.execute(select(Permanencia.trayectoria_id, Permanencia.continua_matriculado)
                                     .where(Permanencia.trayectoria_id.in_([t.id for t in trayect.values()]))).all():
            perm[t_id] = bool(cont)

    def bloque(est_ids: set[int], semaforo: dict[str, int]) -> dict[str, Any]:
        n = len(est_ids)
        tipos: dict[str, int] = defaultdict(int)
        for e in est_ids:
            for t in barreras.get(e, {}):
                tipos[t] += 1
        cont = sum(1 for e in est_ids if e in trayect and perm.get(trayect[e].id) is True)
        no_cont = sum(1 for e in est_ids if e in trayect and perm.get(trayect[e].id) is False)
        con_dato = cont + no_cont
        pdist = sup.distribucion({"continuan": cont, "no_continuan": no_cont})
        tasa = round(cont * 100 / con_dato, 1) if con_dato >= k and None not in pdist.values() else None
        visible = n == 0 or n >= k
        return {
            "planes_activos": sup.cell(n),
            "semaforo": sup.distribucion(semaforo) if visible else dict.fromkeys(semaforo),
            "tipos_barrera": {t: sup.cell(c) for t, c in sorted(tipos.items())} if visible else {},
            "permanencia": {**pdist, "tasa_permanencia_pct": tasa} if visible else
            {"continuan": None, "no_continuan": None, "tasa_permanencia_pct": None},
        }

    filas = []
    ocultos = False
    for p in progs:
        b = bloque(est_por_prog.get(p.id, set()), sem_por_prog[p.id] if p.id in sem_por_prog else
                   {"VERDE": 0, "AMARILLO": 0, "ROJO": 0, "SIN_REGISTRO": 0})
        if b["planes_activos"] is None and len(est_por_prog.get(p.id, ())) > 0:
            ocultos = True
        filas.append({"programa_id": p.id, "programa": p.nombre_programa, **b})
    tot_sem = {"VERDE": 0, "AMARILLO": 0, "ROJO": 0, "SIN_REGISTRO": 0}
    for d in sem_por_prog.values():
        for c, n in d.items():
            tot_sem[c] += n
    totales = bloque(all_est, tot_sem)
    if ocultos and len(filas) > 1:  # evita recuperar un programa oculto restando del total
        totales = {"planes_activos": None, "semaforo": dict.fromkeys(tot_sem), "tipos_barrera": {},
                   "permanencia": {"continuan": None, "no_continuan": None, "tasa_permanencia_pct": None}}
        sup.suprimidas += 1
    return {**_cabecera(user, progs, k, programa_id=programa_id, semestre=semestre), "programas": filas,
            "totales": totales, "celdas_suprimidas": sup.suprimidas}


# ----------------------------------------------------------------------------- trayectorias
REFERENCIA_KEYS = ("permanencia_pct", "avance_promedio_pct", "graduacion_pct", "promedio_academico")


def referencia_clave(programa_id: int) -> str:
    return f"referencia_programa:{programa_id}"


def get_referencia(db: Session, programa_id: int) -> dict[str, Any]:
    v = params.get_param(db, referencia_clave(programa_id), {})
    return v if isinstance(v, dict) else {}


def trayectorias(db: Session, user: Usuario, programa_id: int | None = None, semestre: str | None = None,
                 override: dict[str, float | None] | None = None) -> dict[str, Any]:
    progs = resolve_scope(db, user, programa_id)
    k = k_minimo(db)
    sup = Supresor(k)
    planes = _planes_activos(db, [p.id for p in progs], None)
    por_prog: dict[int, set[int]] = defaultdict(set)
    for _p, est, _s, prog in planes:
        por_prog[prog].add(est)
    filas = []
    for p in progs:
        ests = por_prog.get(p.id, set())
        tray = {e: t for e, t in _latest_trayectoria(db, ests).items() if not semestre or t.semestre_academico == semestre}
        tids = [t.id for t in tray.values()]
        perm = dict(db.execute(select(Permanencia.trayectoria_id, Permanencia.continua_matriculado)
                               .where(Permanencia.trayectoria_id.in_(tids or [-1]))).all())
        prog_av = dict(db.execute(select(Progresion.trayectoria_id, Progresion.avance_plan_estudios_porcentaje)
                                  .where(Progresion.trayectoria_id.in_(tids or [-1]))).all())
        grad = dict(db.execute(select(Graduacion.trayectoria_id, Graduacion.ha_graduado)
                               .where(Graduacion.trayectoria_id.in_(tids or [-1]))).all())
        n = len(tray)
        visible = n >= k
        cont = sum(1 for t in tids if perm.get(t) is True)
        no_cont = sum(1 for t in tids if perm.get(t) is False)
        pd = sup.distribucion({"continuan": cont, "no_continuan": no_cont}) if visible else {"continuan": None, "no_continuan": None}
        permanencia = round(cont * 100 / (cont + no_cont), 1) if visible and (cont + no_cont) >= k and None not in pd.values() else None
        avs = [v for v in prog_av.values() if v is not None]
        avance = round(sum(avs) / len(avs), 1) if visible and len(avs) >= k else None
        proms = [float(t.promedio_academico) for t in tray.values() if t.promedio_academico is not None]
        promedio = round(sum(proms) / len(proms), 2) if visible and len(proms) >= k else None
        grads = [bool(v) for v in grad.values() if v is not None]
        graduacion = None
        if visible and len(grads) >= k:
            g = sup.distribucion({"graduados": sum(grads), "no_graduados": len(grads) - sum(grads)})
            graduacion = round(sum(grads) * 100 / len(grads), 1) if None not in g.values() else None
        if not visible and n:
            sup.suprimidas += 1
        cohorte = {"permanencia_pct": permanencia, "avance_promedio_pct": avance, "graduacion_pct": graduacion,
                   "promedio_academico": promedio}
        ref = dict(get_referencia(db, p.id))
        for kk, vv in (override or {}).items():
            if vv is not None:
                ref[kk] = vv
        comparacion = {}
        for kk in REFERENCIA_KEYS:
            r, c = ref.get(kk), cohorte[kk]
            comparacion[kk] = {"cohorte_tea": c, "referencia_programa": r,
                               "diferencia": round(c - r, 2) if c is not None and r is not None else None}
        filas.append({"programa_id": p.id, "programa": p.nombre_programa, "estudiantes_con_trayectoria": sup.cell(n),
                      "permanencia": pd, "indicadores": comparacion, "referencia_fuente": ref.get("fuente")})
    return {**_cabecera(user, progs, k, programa_id=programa_id, semestre=semestre), "programas": filas,
            "celdas_suprimidas": sup.suprimidas}


# ----------------------------------------------------------------------------- ajustes frecuentes
_RESP = (
    ("COMUNICACION", RespuestaComunicacion, "tipo_comunicacion_ajuste"), ("PEDAGOGIA", RespuestaPedagogia, "tipo_pedagogico_ajuste"),
    ("EVALUACION", RespuestaEvaluacion, "tipo_evaluativo_ajuste"), ("AMBIENTE", RespuestaAmbiente, "tipo_ambiental_ajuste"),
    ("INTERACCION", RespuestaInteraccion, "tipo_interaccion_ajuste"), ("TECNOLOGIA", RespuestaTecnologia, "tipo_tecnologico_ajuste"),
)


def ajustes_frecuentes(db: Session, user: Usuario, programa_id: int | None = None, semestre: str | None = None,
                       top: int = 15) -> dict[str, Any]:
    progs = resolve_scope(db, user, programa_id)
    k = k_minimo(db)
    sup = Supresor(k)
    stmt = (
        select(AjusteRazonable.id, AjusteRazonable.tipo_ajuste, PlanMaarTea.estudiante_id)
        .join(PlanMaarTea, PlanMaarTea.id == AjusteRazonable.plan_id)
        .join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id)
        .where(Estudiante.programa_id.in_([p.id for p in progs] or [-1]))
    )
    if semestre:
        stmt = stmt.where(PlanMaarTea.semestre_academico == semestre)
    ajustes = db.execute(stmt).all()
    por_aj = {a: (str(t), e) for a, t, e in ajustes}
    cat: dict[str, dict[str, set]] = defaultdict(lambda: {"est": set(), "aj": set()})
    for a, (t, e) in por_aj.items():
        cat[t]["est"].add(e)
        cat[t]["aj"].add(a)
    sub: dict[tuple[str, str], dict[str, set]] = defaultdict(lambda: {"est": set(), "aj": set()})
    if por_aj:
        for categoria, modelo, col in _RESP:
            for aj_id, tipo in db.execute(select(modelo.ajuste_id, getattr(modelo, col)).where(modelo.ajuste_id.in_(por_aj))).all():
                d = sub[(categoria, str(tipo))]
                d["est"].add(por_aj[aj_id][1])
                d["aj"].add(aj_id)

    def filas(items):
        visibles, ocultas = [], 0
        for clave, d in sorted(items, key=lambda kv: (-len(kv[1]["est"]), str(kv[0]))):
            n = len(d["est"])
            if n < k:
                ocultas += 1
                sup.suprimidas += 1
                continue
            visibles.append((clave, n, len(d["aj"])))
        return visibles[:top], ocultas

    cats, cats_ocultas = filas(cat.items())
    subs, subs_ocultas = filas(sub.items())
    return {
        **_cabecera(user, progs, k, programa_id=programa_id, semestre=semestre),
        "categorias": [{"categoria": c, "estudiantes": n, "ajustes": a} for c, n, a in cats],
        "categorias_ocultas": cats_ocultas,
        "ajustes_especificos": [{"categoria": c[0], "tipo": c[1], "estudiantes": n, "ajustes": a} for c, n, a in subs],
        "ajustes_especificos_ocultos": subs_ocultas, "celdas_suprimidas": sup.suprimidas,
    }


# ----------------------------------------------------------------------------- efectividad DUA
def efectividad_dua(db: Session, user: Usuario, programa_id: int | None = None, semestre: str | None = None,
                    top: int = 20) -> dict[str, Any]:
    progs = resolve_scope(db, user, programa_id)
    k = k_minimo(db)
    sup = Supresor(k)
    stmt = (
        select(EstrategiaDua, PlanMaarTea.estudiante_id)
        .join(PlanMaarTea, PlanMaarTea.id == EstrategiaDua.plan_id)
        .join(Estudiante, Estudiante.id == PlanMaarTea.estudiante_id)
        .where(EstrategiaDua.estrategia_catalogo_id.is_not(None), Estudiante.programa_id.in_([p.id for p in progs] or [-1]))
    )
    if semestre:
        stmt = stmt.where(PlanMaarTea.semestre_academico == semestre)
    por_est: dict[int, dict[str, Any]] = defaultdict(lambda: {"est": set(), "plans": set(), "impl": 0, "tot": 0})
    plan_ids: set[int] = set()
    for e, est_id in db.execute(stmt).all():
        d = por_est[e.estrategia_catalogo_id]
        d["est"].add(est_id)
        d["plans"].add(e.plan_id)
        d["tot"] += 1
        d["impl"] += 1 if (e.implementada is True or str(e.estado_implementacion) == "IMPLEMENTADA") else 0
        plan_ids.add(e.plan_id)
    casos: dict[int, list[bool]] = defaultdict(list)
    if plan_ids:
        for ec, ok in db.execute(select(CasoCbr.estrategia_catalogo_id, CasoCbr.exitoso).where(CasoCbr.plan_id.in_(plan_ids))).all():
            casos[ec].append(bool(ok))
    cat = {c.id: c for c in db.scalars(select(EstrategiaDuaCatalogo).where(EstrategiaDuaCatalogo.id.in_(por_est or [-1])))}
    filas, ocultas = [], 0
    por_principio: dict[str, dict[str, Any]] = defaultdict(lambda: {"est": set(), "impl": 0, "tot": 0})
    for cid, d in por_est.items():
        c = cat.get(cid)
        if c is None:
            continue
        pp = por_principio[str(c.principio)]
        pp["est"] |= d["est"]
        pp["impl"] += d["impl"]
        pp["tot"] += d["tot"]
        n = len(d["est"])
        if n < k:
            ocultas += 1
            sup.suprimidas += 1
            continue
        cs = casos.get(cid, [])
        filas.append({
            "estrategia_id": cid, "codigo": c.codigo, "nombre": c.nombre, "principio": str(c.principio), "pauta": c.pauta,
            "estudiantes": n, "tasa_implementacion_pct": round(d["impl"] * 100 / d["tot"], 1) if d["tot"] else None,
            "casos_evaluados": len(cs) if len(cs) >= k else None,
            "tasa_efectividad_pct": round(sum(cs) * 100 / len(cs), 1) if len(cs) >= k else None,
        })
    filas.sort(key=lambda f: (-f["estudiantes"], f["codigo"]))
    principios = []
    for pr, d in sorted(por_principio.items()):
        visible = len(d["est"]) >= k
        if not visible:
            sup.suprimidas += 1
        principios.append({"principio": pr, "estudiantes": len(d["est"]) if visible else None,
                           "tasa_implementacion_pct": round(d["impl"] * 100 / d["tot"], 1) if visible and d["tot"] else None})
    return {**_cabecera(user, progs, k, programa_id=programa_id, semestre=semestre), "estrategias": filas[:top],
            "estrategias_ocultas": ocultas, "por_principio": principios, "celdas_suprimidas": sup.suprimidas}


# ----------------------------------------------------------------------------- uso (HU-27, solo ADMIN)
def uso(db: Session, user: Usuario, desde: date | None = None, hasta: date | None = None) -> dict[str, Any]:
    if str(user.rol) != Rol.ADMIN:
        raise Forbidden("Los reportes de uso del sistema son solo para el administrador.", "ROL_NO_PERMITIDO")
    k = k_minimo(db)
    sup = Supresor(k)
    hasta = hasta or date.today()
    desde = desde or hasta - timedelta(days=180)
    d0 = datetime.combine(desde, datetime.min.time()).replace(tzinfo=utcnow().tzinfo)
    d1 = datetime.combine(hasta + timedelta(days=1), datetime.min.time()).replace(tzinfo=utcnow().tzinfo)

    roles: dict[str, dict[str, int | None]] = defaultdict(dict)
    for rol, estado, n in db.execute(select(Usuario.rol, Usuario.estado, func.count()).group_by(Usuario.rol, Usuario.estado)).all():
        roles[str(rol)][str(estado)] = sup.cell(n) if str(rol) in ("ESTUDIANTE", "FAMILIAR") else n
    vias = {str(v): sup.cell(n) for v, n in db.execute(select(Estudiante.via_ingreso, func.count()).group_by(Estudiante.via_ingreso)).all()}
    planes_estado = {str(e): n for e, n in db.execute(select(PlanMaarTea.estado, func.count()).group_by(PlanMaarTea.estado)).all()}
    por_sem: dict[str, dict[str, int]] = defaultdict(lambda: {"planes": 0, "VERDE": 0, "AMARILLO": 0, "ROJO": 0, "SIN_REGISTRO": 0})
    for sem, semaforo, n in db.execute(select(PlanMaarTea.semestre_academico, PlanMaarTea.semaforo_actual, func.count())
                                       .group_by(PlanMaarTea.semestre_academico, PlanMaarTea.semaforo_actual)).all():
        por_sem[sem]["planes"] += n
        por_sem[sem][str(semaforo) if semaforo else "SIN_REGISTRO"] += n
    semestres = []
    for sem, d in sorted(por_sem.items()):
        visible = d["planes"] >= k
        sd = sup.distribucion({c: d[c] for c in ("VERDE", "AMARILLO", "ROJO", "SIN_REGISTRO")}) if visible else None
        if not visible:
            sup.suprimidas += 1
        semestres.append({"semestre": sem, "planes_generados": d["planes"] if visible else None, "semaforo": sd})
    logins = db.scalar(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.accion == "LOGIN_OK", LogAuditoria.created_at >= d0, LogAuditoria.created_at < d1)) or 0
    notifs = db.scalar(select(func.count()).select_from(Notificacion).where(Notificacion.created_at >= d0, Notificacion.created_at < d1)) or 0
    correos = {str(e): n for e, n in db.execute(select(EmailOutbox.estado, func.count()).where(
        EmailOutbox.created_at >= d0, EmailOutbox.created_at < d1).group_by(EmailOutbox.estado)).all()}
    exports = {str(t): n for t, n in db.execute(select(Exportacion.tipo, func.count()).where(
        Exportacion.created_at >= d0, Exportacion.created_at < d1).group_by(Exportacion.tipo)).all()}
    return {
        "k_minimo": k, "generado_at": utcnow().isoformat(), "alcance": {"rol": "ADMIN", "programas": []},
        "filtros": {"desde": desde.isoformat(), "hasta": hasta.isoformat()}, "nota_privacidad": NOTA_SUPRESION.format(k=k),
        "usuarios_por_rol_estado": roles, "estudiantes_por_via_ingreso": vias, "planes_por_estado": planes_estado,
        "planes_por_semestre": semestres,
        "actividad": {"inicios_de_sesion": int(logins), "notificaciones_creadas": int(notifs), "correos_por_estado": correos,
                      "exportaciones_por_tipo": exports},
        "celdas_suprimidas": sup.suprimidas,
    }


def build_report(db: Session, user: Usuario, tipo: str, *, programa_id: int | None = None, semestre: str | None = None,
                 desde: date | None = None, hasta: date | None = None) -> dict[str, Any]:
    if tipo == "dashboard":
        return dashboard(db, user, programa_id, semestre)
    if tipo == "trayectorias":
        return trayectorias(db, user, programa_id, semestre)
    if tipo == "ajustes-frecuentes":
        return ajustes_frecuentes(db, user, programa_id, semestre)
    if tipo == "efectividad-dua":
        return efectividad_dua(db, user, programa_id, semestre)
    return uso(db, user, desde, hasta)


# ----------------------------------------------------------------------------- tablas para exportar
def _v(x: Any) -> Any:
    return "—" if x is None else x


def tablas(tipo: str, d: dict[str, Any]) -> list[dict[str, Any]]:
    if tipo == "dashboard":
        filas = []
        for p in [*d["programas"], {"programa": "TOTAL", **d["totales"]}]:
            s, pe = p["semaforo"], p["permanencia"]
            filas.append([p["programa"], _v(p["planes_activos"]), _v(s.get("VERDE")), _v(s.get("AMARILLO")), _v(s.get("ROJO")),
                          _v(s.get("SIN_REGISTRO")), _v(pe.get("tasa_permanencia_pct"))])
        barr = []
        for p in [*d["programas"], {"programa": "TOTAL", **d["totales"]}]:
            for t, n in p["tipos_barrera"].items():
                barr.append([p["programa"], t, _v(n)])
        return [{"titulo": "Planes activos, semáforo y permanencia",
                 "columnas": ["Programa", "Planes activos", "Verde", "Amarillo", "Rojo", "Sin registro", "Permanencia %"], "filas": filas},
                {"titulo": "Tipos de barrera (estudiantes)", "columnas": ["Programa", "Tipo de barrera", "Estudiantes"], "filas": barr}]
    if tipo == "trayectorias":
        filas = []
        for p in d["programas"]:
            for ind, c in p["indicadores"].items():
                filas.append([p["programa"], ind, _v(c["cohorte_tea"]), _v(c["referencia_programa"]), _v(c["diferencia"])])
        return [{"titulo": "Cohorte TEA frente al promedio del programa",
                 "columnas": ["Programa", "Indicador", "Cohorte TEA", "Referencia del programa", "Diferencia"], "filas": filas}]
    if tipo == "ajustes-frecuentes":
        return [
            {"titulo": "Categorías de ajuste", "columnas": ["Categoría", "Estudiantes", "Ajustes"],
             "filas": [[c["categoria"], c["estudiantes"], c["ajustes"]] for c in d["categorias"]]},
            {"titulo": "Ajustes específicos", "columnas": ["Categoría", "Tipo", "Estudiantes", "Ajustes"],
             "filas": [[c["categoria"], c["tipo"], c["estudiantes"], c["ajustes"]] for c in d["ajustes_especificos"]]},
        ]
    if tipo == "efectividad-dua":
        return [{"titulo": "Estrategias DUA", "columnas": ["Código", "Estrategia", "Principio", "Estudiantes", "Implementación %",
                                                           "Casos", "Efectividad %"],
                 "filas": [[e["codigo"], e["nombre"], e["principio"], e["estudiantes"], _v(e["tasa_implementacion_pct"]),
                            _v(e["casos_evaluados"]), _v(e["tasa_efectividad_pct"])] for e in d["estrategias"]]}]
    filas_u = [[r, e, _v(n)] for r, es in d["usuarios_por_rol_estado"].items() for e, n in es.items()]
    filas_s = [[s["semestre"], _v(s["planes_generados"]), *[_v((s["semaforo"] or {}).get(c)) for c in ("VERDE", "AMARILLO", "ROJO")]]
               for s in d["planes_por_semestre"]]
    a = d["actividad"]
    return [{"titulo": "Usuarios por rol y estado", "columnas": ["Rol", "Estado", "Cuentas"], "filas": filas_u},
            {"titulo": "Planes por semestre", "columnas": ["Semestre", "Planes", "Verde", "Amarillo", "Rojo"], "filas": filas_s},
            {"titulo": "Actividad", "columnas": ["Indicador", "Valor"],
             "filas": [["Inicios de sesión", a["inicios_de_sesion"]], ["Notificaciones creadas", a["notificaciones_creadas"]]]}]


TITULOS = {"dashboard": "Dashboard de inclusión", "trayectorias": "Trayectorias: cohorte TEA vs. programa",
           "ajustes-frecuentes": "Ajustes razonables más frecuentes", "efectividad-dua": "Efectividad de estrategias DUA",
           "uso": "Uso del sistema"}


def _safe_cell(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def to_xlsx(tipo: str, d: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Resumen"
    ws0.append([TITULOS[tipo]])
    ws0["A1"].font = Font(bold=True, size=14)
    ws0.append(["Generado", d["generado_at"]])
    ws0.append(["Alcance", ", ".join(p["nombre"] for p in d["alcance"]["programas"]) or "Institucional"])
    ws0.append(["Mínimo por celda (k)", d["k_minimo"]])
    ws0.append([d["nota_privacidad"]])
    for i, t in enumerate(tablas(tipo, d), start=1):
        ws = wb.create_sheet(f"{i}-{t['titulo']}"[:31].replace("/", "-").replace(":", ""))
        ws.append(t["columnas"])
        for c in ws[1]:
            c.font = Font(bold=True)
        for f in t["filas"]:
            ws.append([_safe_cell(x) for x in f])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(60, max(12, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_html(tipo: str, d: dict[str, Any]) -> str:
    partes = [f"<h1>{html.escape(TITULOS[tipo])}</h1>",
              f"<p>Alcance: {html.escape(', '.join(p['nombre'] for p in d['alcance']['programas']) or 'Institucional')} · "
              f"Generado: {html.escape(d['generado_at'][:19])}</p>"]
    for t in tablas(tipo, d):
        partes.append(f"<h2>{html.escape(t['titulo'])}</h2><table><thead><tr>"
                      + "".join(f"<th>{html.escape(c)}</th>" for c in t["columnas"]) + "</tr></thead><tbody>"
                      + "".join("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in f) + "</tr>" for f in t["filas"])
                      + "</tbody></table>")
    partes.append(f"<p class='nota'>{html.escape(d['nota_privacidad'])} Los datos son agregados y no identifican a nadie.</p>")
    css = ("body{font-family:Arial,sans-serif;margin:24px;color:#111}table{border-collapse:collapse;width:100%;margin:8px 0 20px}"
           "th,td{border:1px solid #999;padding:6px 8px;text-align:left;font-size:12px}th{background:#eee}.nota{font-size:11px;color:#444}")
    return f"<!doctype html><html lang='es'><head><meta charset='utf-8'><title>{html.escape(TITULOS[tipo])}</title><style>{css}</style></head><body>{''.join(partes)}</body></html>"


def to_pdf(tipo: str, d: dict[str, Any]) -> tuple[bytes, bool]:
    """(contenido, es_pdf). Si WeasyPrint no está disponible devuelve HTML imprimible (es_pdf=False)."""
    doc = to_html(tipo, d)
    try:
        from weasyprint import HTML

        return HTML(string=doc).write_pdf(), True
    except Exception as exc:  # noqa: BLE001 - ImportError u OSError (librerías nativas ausentes)
        logger.warning("WeasyPrint no disponible; se entrega HTML imprimible: %s", exc)
        return doc.encode("utf-8"), False
