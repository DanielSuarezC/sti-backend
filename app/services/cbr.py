"""Motor DUA M3 (RF-15/16): razonamiento basado en casos (CBR) con scikit-learn + reglas sobre el catálogo.

* Perfil abstracto (NO identificatorio): tipos de barrera, escenarios, severidad, principios y rasgos funcionales
  (solo valores de enum: p. ej. `SENS_AUDITIVA`, `AUTONOMIA_BAJA`). Nunca nombre, puntaje AQ-10, diagnóstico ni ids.
* Similitud coseno (DictVectorizer ponderado) entre el perfil de la barrera y los `CASO_CBR`; el puntaje de cada
  estrategia combina la similitud con la efectividad registrada (semáforo F8/F9). Rechazos de Bienestar entran como
  casos negativos (retroalimentación).
* Con menos de `MIN_CASOS` casos relevantes, recomienda por reglas (tipo de barrera + escenario) sobre el catálogo.
* Sugiere, nunca impone. Este módulo no habla con la IA (eso es `ai_gateway`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.caracterizacion import DatoAutonomia, DatoSensorial
from app.models.dua import CasoCbr, EstrategiaDuaCatalogo, SugerenciaDua
from app.models.enums import (
    NivelAutonomia,
    OrigenSugerencia,
    PrincipioDua,
    Semaforo,
    Severidad,
)
from app.models.mapa import BarreraIdentificada
from app.services.b_common import semestre_de
from app.services.caracterizacion import current_f1

MIN_CASOS = 3  # casos relevantes mínimos para usar CBR; por debajo se usan reglas
UMBRAL_SIMILITUD = 0.35
PESOS = {"T": 3.0, "E": 2.0, "S": 1.0, "R": 1.0, "P": 1.0}
EFECTIVIDAD = {Semaforo.VERDE: 1.0, Semaforo.AMARILLO: 0.5, Semaforo.ROJO: -0.5}
PRINCIPIO_NOMBRE = {
    PrincipioDua.REPRESENTACION: "Múltiples formas de representación",
    PrincipioDua.ACCION_EXPRESION: "Múltiples formas de acción y expresión",
    PrincipioDua.PARTICIPACION: "Múltiples formas de participación e implicación",
}


@dataclass
class Recomendacion:
    barrera_id: int
    estrategia: EstrategiaDuaCatalogo
    puntaje: float
    origen: OrigenSugerencia
    justificacion: str
    tipo_barrera: str
    escenario: str | None
    principio: str
    casos_similares: int = 0
    porcentaje_exito: float | None = None
    detalle: dict[str, Any] = field(default_factory=dict)


# ============================================================================ perfil
def functional_traits(db: Session, estudiante_id: int) -> list[str]:
    """Rasgos funcionales como etiquetas de enum (sin texto libre, sin identidad)."""
    car = current_f1(db, estudiante_id)
    if car is None:
        return []
    rasgos: set[str] = set()
    for s in db.scalars(select(DatoSensorial).where(DatoSensorial.caracterizacion_id == car.id)):
        if s.hipersensibilidad or s.hiposensibilidad:
            rasgos.add(f"SENS_{s.tipo_sensorial}")
    for a in db.scalars(select(DatoAutonomia).where(DatoAutonomia.caracterizacion_id == car.id)):
        if a.nivel_autonomia == NivelAutonomia.BAJA:
            rasgos.add("AUTONOMIA_BAJA")
    return sorted(rasgos)


def _features(tipos: list[str], escenarios: list[str], severidad: str | None, rasgos: list[str], principios: list[str]) -> dict[str, float]:
    f: dict[str, float] = {}
    for t in tipos:
        f[f"T:{t}"] = PESOS["T"]
    for e in escenarios:
        f[f"E:{e}"] = PESOS["E"]
    if severidad:
        f[f"S:{severidad}"] = PESOS["S"]
    for r in rasgos:
        f[f"R:{r}"] = PESOS["R"]
    for p in principios:
        f[f"P:{p}"] = PESOS["P"]
    return f


def case_features(c: CasoCbr) -> dict[str, float]:
    p = c.perfil or {}
    return _features(list(p.get("tipos_barrera", [])), list(p.get("escenarios", [])), p.get("severidad_max"),
                     list(p.get("rasgos", [])), list(p.get("principios", [])))


def _case_effect(c: CasoCbr) -> float:
    if c.resultado_semaforo is not None:
        return EFECTIVIDAD[Semaforo(str(c.resultado_semaforo))]
    return 0.6 if c.exitoso else -0.5


def profile_of(b: BarreraIdentificada, rasgos: list[str], principio: str) -> dict[str, Any]:
    return {"tipos_barrera": [str(b.tipo_barrera)], "escenarios": [str(b.escenario)] if b.escenario else [],
            "principios": [principio], "severidad_max": str(b.severidad), "rasgos": rasgos}


# ============================================================================ similitud
def _similarities(queries: list[dict[str, float]], cases: list[dict[str, float]]) -> list[list[float]]:
    """Matriz queries x cases de similitud coseno (scikit-learn)."""
    if not queries or not cases:
        return [[] for _ in queries]
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    vec = DictVectorizer(sparse=False)
    vec.fit(queries + cases)
    sims = cosine_similarity(vec.transform(queries), vec.transform(cases))
    return sims.tolist()


# ============================================================================ recomendación
def _rule_score(e: EstrategiaDuaCatalogo, tipo: str, esc: str | None) -> float | None:
    tipos = [str(t) for t in (e.tipos_barrera or [])]
    escs = [str(x) for x in (e.escenarios or [])]
    if tipos and tipo not in tipos:
        return None  # no resuelve este tipo de barrera
    t = 1.0 if tipos else 0.5
    s = 0.0
    if esc and esc in escs:
        s = 0.5
    elif not escs:
        s = 0.25
    return (t + s) / 1.5


def recommend_for_barrier(db: Session, b: BarreraIdentificada, rasgos: list[str], catalogo: list[EstrategiaDuaCatalogo],
                          casos: list[CasoCbr], *, max_por_barrera: int = 3, excluir: set[int] | None = None) -> list[Recomendacion]:
    excluir = excluir or set()
    tipo, esc = str(b.tipo_barrera), (str(b.escenario) if b.escenario else None)
    principios = [str(p) for p in PrincipioDua]
    queries = [_features([tipo], [esc] if esc else [], str(b.severidad), rasgos, [p]) for p in principios]
    sims = _similarities(queries, [case_features(c) for c in casos])
    sim_por_principio = dict(zip(principios, sims, strict=True))
    # ¿hay evidencia suficiente? casos relevantes (similitud >= umbral) para cualquier estrategia candidata
    relevantes_total = sum(1 for p in principios for s in sim_por_principio[p] if s >= UMBRAL_SIMILITUD)
    modo_cbr = relevantes_total >= MIN_CASOS
    out: list[Recomendacion] = []
    for e in catalogo:
        if e.id in excluir:
            continue
        regla = _rule_score(e, tipo, esc)
        if regla is None:
            continue
        sim_row = sim_por_principio[str(e.principio)]
        rel = [(s, c) for s, c in zip(sim_row, casos, strict=True) if c.estrategia_catalogo_id == e.id and s >= UMBRAL_SIMILITUD]
        neg = sum(1 for _s, c in rel if _case_effect(c) < 0)
        pct = None
        score = 0.4 * regla if modo_cbr else regla  # sin evidencia: aporte CBR neutro (0)
        origen = OrigenSugerencia.FILTRO_CATALOGO
        if rel:
            w = [s * (c.peso or 1.0) for s, c in rel]
            eff = sum(wi * _case_effect(c) for wi, (_s, c) in zip(w, rel, strict=True)) / sum(w)
            pos = sum(1 for _s, c in rel if _case_effect(c) > 0)
            pct = round(100 * pos / len(rel))
            if modo_cbr:
                mean_sim = sum(s for s, _c in rel) / len(rel)
                cbr = max(-0.5, min(1.0, eff * mean_sim * min(1.0, len(rel) / 3)))
                score = 0.4 * regla + 0.6 * cbr
                origen = OrigenSugerencia.CBR
            else:
                score = regla - min(0.3, 0.1 * neg)
        score = max(0.0, min(1.0, score))
        if score <= 0:
            continue
        out.append(Recomendacion(
            barrera_id=b.id, estrategia=e, puntaje=round(score, 4), origen=origen, tipo_barrera=tipo, escenario=esc,
            principio=str(e.principio), casos_similares=len(rel), porcentaje_exito=pct,
            justificacion=justify(e, b, len(rel) if origen == OrigenSugerencia.CBR else 0, pct if origen == OrigenSugerencia.CBR else None),
            detalle={"modo": "CBR" if modo_cbr else "REGLAS", "regla": round(regla, 3)},
        ))
    out.sort(key=lambda r: (-r.puntaje, r.estrategia.codigo))
    return out[:max_por_barrera]


def justify(e: EstrategiaDuaCatalogo, b: BarreraIdentificada, n_casos: int, pct: float | None) -> str:
    tipo = str(b.tipo_barrera)
    esc = str(b.escenario) if b.escenario else None
    base = (f"Esta estrategia es pertinente porque el estudiante tiene barrera de tipo {tipo} en el escenario {esc}."
            if esc else f"Esta estrategia es pertinente porque el estudiante tiene barrera de tipo {tipo} en el contexto universitario.")
    partes = [base, f"Corresponde al principio DUA «{PRINCIPIO_NOMBRE[PrincipioDua(str(e.principio))]}» "
                    f"(pauta {e.pauta}{': ' + e.pauta_nombre if e.pauta_nombre else ''})."]
    if esc and esc in [str(x) for x in (e.escenarios or [])]:
        partes.append("El catálogo institucional la recomienda para ese escenario.")
    elif not (e.escenarios or []):
        partes.append("Es una medida general que sirve en varios escenarios.")
    if n_casos:
        partes.append(f"En {n_casos} caso(s) anterior(es) de perfil similar, esta estrategia mostró buenos resultados en {pct}% de ellos.")
    if b.severidad == Severidad.SEVERA:
        partes.append("La barrera se registró como severa, por eso se prioriza.")
    partes.append("Es una sugerencia: usted decide si la acepta, la modifica o la rechaza.")
    return " ".join(partes)


def recommend(db: Session, estudiante_id: int, barreras: list[BarreraIdentificada], *, max_por_barrera: int = 3,
              excluir_por_barrera: dict[int, set[int]] | None = None) -> tuple[list[Recomendacion], list[int]]:
    """Recomendaciones para las barreras dadas. Devuelve (recomendaciones, ids de barreras sin cobertura)."""
    catalogo = list(db.scalars(select(EstrategiaDuaCatalogo).where(EstrategiaDuaCatalogo.activo.is_(True)).order_by(EstrategiaDuaCatalogo.id)))
    casos = list(db.scalars(select(CasoCbr)))
    rasgos = functional_traits(db, estudiante_id)
    out: list[Recomendacion] = []
    sin: list[int] = []
    for b in barreras:
        recs = recommend_for_barrier(db, b, rasgos, catalogo, casos, max_por_barrera=max_por_barrera,
                                     excluir=(excluir_por_barrera or {}).get(b.id))
        if not recs:
            sin.append(b.id)
        out.extend(recs)
    return out, sin


def register_rejection(db: Session, s: SugerenciaDua) -> CasoCbr:
    """Retroalimentación: un rechazo se guarda como caso NEGATIVO anónimo (sin ids de persona ni de plan)."""
    b = db.get(BarreraIdentificada, s.barrera_id) if s.barrera_id else None
    perfil = {"tipos_barrera": [str(s.tipo_barrera)] if s.tipo_barrera else [], "escenarios": [str(s.escenario)] if s.escenario else [],
              "principios": [str(s.principio_dua)], "severidad_max": str(b.severidad) if b else None,
              "rasgos": functional_traits(db, s.estudiante_id)}
    c = CasoCbr(estrategia_catalogo_id=s.estrategia_catalogo_id, perfil=perfil, exitoso=False, peso=0.5,
                semestre_academico=semestre_de(), origen="RECHAZO_BIENESTAR", fecha_caso=date.today())
    db.add(c)
    db.flush()
    return c


