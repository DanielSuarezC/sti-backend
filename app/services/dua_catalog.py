"""Catálogo DUA (M1, RF-14, HU-01): validación, importación CSV/JSON con dry-run y exportación.

Formato de importación (CSV con encabezados o JSON: lista de objetos o `{"estrategias": [...]}`):

    codigo, nombre, descripcion_pedagogica, principio, pauta, punto_verificacion, escenarios, tipos_barrera,
    perfil_estudiante, fuente, activo

* `principio`: REPRESENTACION | ACCION_EXPRESION | PARTICIPACION. `pauta`: 1-9 (CAST 2.2; 1-3 = representación,
  4-6 = acción y expresión, 7-9 = participación). `punto_verificacion`: p. ej. `2.2` (debe empezar por la pauta).
* `escenarios` y `tipos_barrera`: listas; en CSV separadas por `|` (también `;` si el CSV usa coma), en JSON arreglos.
* Importación idempotente por `codigo`: si ya existe se omite (`EXISTENTE`) salvo `actualizar_existentes=true`.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import AppError, Unprocessable
from app.data.dua_cast import PAUTAS, PRINCIPIOS
from app.models.dua import EstrategiaDuaCatalogo
from app.models.enums import Escenario, PrincipioDua, TipoBarrera
from app.models.usuarios import Usuario
from app.services.csv_import import MAX_BYTES, MAX_FILAS, decode_bytes, read_csv_rows

CAMPOS = [
    "codigo", "nombre", "descripcion_pedagogica", "principio", "pauta", "pauta_nombre", "punto_verificacion",
    "escenarios", "tipos_barrera", "perfil_estudiante", "fuente", "activo",
]
_PUNTO_RE = re.compile(r"^[1-9]\.[1-9]$")


def principios_y_pautas() -> list[dict[str, Any]]:
    """Los 3 principios CAST 2.2 con sus pautas y puntos de verificación."""
    out = []
    for principio, titulo in PRINCIPIOS.items():
        pautas = []
        for numero, (princ, nombre, puntos) in PAUTAS.items():
            if princ == principio:
                pautas.append({
                    "pauta": numero, "nombre": nombre,
                    "puntos_verificacion": [{"punto": p, "texto": t} for p, t in puntos],
                })
        out.append({"principio": principio, "nombre": titulo, "pautas": pautas})
    return out


def pauta_principio(pauta: int) -> str:
    return PAUTAS[pauta][0]


def serialize(e: EstrategiaDuaCatalogo) -> dict[str, Any]:
    return {
        "id": e.id, "codigo": e.codigo, "nombre": e.nombre, "descripcion_pedagogica": e.descripcion_pedagogica,
        "principio": str(e.principio), "pauta": e.pauta, "pauta_nombre": e.pauta_nombre,
        "punto_verificacion": e.punto_verificacion, "escenarios": list(e.escenarios or []),
        "tipos_barrera": list(e.tipos_barrera or []), "perfil_estudiante": e.perfil_estudiante, "fuente": e.fuente,
        "activo": bool(e.activo), "created_at": e.created_at, "updated_at": e.updated_at,
    }


def _lista(valor: Any, enum_cls: type, campo: str, errs: list[tuple[str, str]]) -> list[str]:
    if valor is None or valor == "":
        return []
    if isinstance(valor, str):
        partes = [p for p in re.split(r"[|;,]", valor) if p.strip()]
    elif isinstance(valor, list):
        partes = [str(p) for p in valor]
    else:
        errs.append((campo, f"{campo} debe ser una lista."))
        return []
    validos = {m.value for m in enum_cls}
    out: list[str] = []
    for p in partes:
        v = p.strip().upper()
        if v not in validos:
            errs.append((campo, f"«{p.strip()}» no es válido en {campo}. Opciones: {', '.join(sorted(validos))}."))
        elif v not in out:
            out.append(v)
    return out


def _bool(valor: Any, default: bool = True) -> bool:
    if valor is None or valor == "":
        return default
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ("1", "true", "si", "sí", "s", "x", "activo", "yes")


def normalize_row(raw: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Valida una fila (CSV o JSON). Devuelve (datos normalizados, errores [(campo, mensaje)])."""
    errs: list[tuple[str, str]] = []
    d: dict[str, Any] = {}
    codigo = str(raw.get("codigo", "") or "").strip()
    if not codigo:
        errs.append(("codigo", "El código es obligatorio."))
    elif len(codigo) > 50:
        errs.append(("codigo", "El código no puede pasar de 50 caracteres."))
    d["codigo"] = codigo
    nombre = str(raw.get("nombre", "") or "").strip()
    if not nombre:
        errs.append(("nombre", "El nombre es obligatorio."))
    elif len(nombre) > 255:
        errs.append(("nombre", "El nombre no puede pasar de 255 caracteres."))
    d["nombre"] = nombre
    desc = str(raw.get("descripcion_pedagogica", "") or "").strip()
    if not desc:
        errs.append(("descripcion_pedagogica", "La descripción pedagógica es obligatoria."))
    d["descripcion_pedagogica"] = desc
    principio = str(raw.get("principio", "") or "").strip().upper()
    if principio not in {m.value for m in PrincipioDua}:
        errs.append(("principio", "El principio debe ser REPRESENTACION, ACCION_EXPRESION o PARTICIPACION."))
    d["principio"] = principio
    pauta_raw = raw.get("pauta")
    pauta: int | None = None
    try:
        pauta = int(str(pauta_raw).strip())
    except (TypeError, ValueError):
        errs.append(("pauta", "La pauta debe ser un número del 1 al 9."))
    if pauta is not None and pauta not in PAUTAS:
        errs.append(("pauta", "La pauta debe ser un número del 1 al 9."))
        pauta = None
    if pauta is not None and principio in {m.value for m in PrincipioDua} and pauta_principio(pauta) != principio:
        errs.append(("pauta", f"La pauta {pauta} pertenece al principio {pauta_principio(pauta)}, no a {principio}."))
    d["pauta"] = pauta
    d["pauta_nombre"] = (str(raw.get("pauta_nombre") or "").strip() or (PAUTAS[pauta][1] if pauta else None))
    punto = str(raw.get("punto_verificacion", "") or "").strip() or None
    if punto is not None:
        if not _PUNTO_RE.match(punto):
            errs.append(("punto_verificacion", "El punto de verificación debe verse como 2.2."))
        elif pauta is not None and not punto.startswith(f"{pauta}."):
            errs.append(("punto_verificacion", f"El punto {punto} no corresponde a la pauta {pauta}."))
    d["punto_verificacion"] = punto
    d["escenarios"] = _lista(raw.get("escenarios"), Escenario, "escenarios", errs)
    d["tipos_barrera"] = _lista(raw.get("tipos_barrera"), TipoBarrera, "tipos_barrera", errs)
    d["perfil_estudiante"] = str(raw.get("perfil_estudiante", "") or "").strip() or None
    fuente = str(raw.get("fuente", "") or "").strip() or None
    if fuente and len(fuente) > 500:
        errs.append(("fuente", "La fuente no puede pasar de 500 caracteres."))
    d["fuente"] = fuente
    d["activo"] = _bool(raw.get("activo"), True)
    return d, errs


def parse_upload(content: bytes, filename: str | None, content_type: str | None) -> list[tuple[int, dict[str, Any]]]:
    """CSV o JSON -> [(posición, fila cruda)]. La posición es el número de línea (CSV) o el índice 1-based (JSON)."""
    if len(content) > MAX_BYTES:
        raise AppError("El archivo es demasiado grande (máximo 2 MB).", "ARCHIVO_MUY_GRANDE", status_code=413)
    nombre = (filename or "").lower()
    es_json = nombre.endswith(".json") or "json" in (content_type or "").lower() or decode_bytes(content).lstrip()[:1] in "[{"
    if es_json:
        try:
            data = json.loads(decode_bytes(content))
        except json.JSONDecodeError as exc:
            raise Unprocessable(f"El JSON no es válido (línea {exc.lineno}): {exc.msg}.", "JSON_INVALIDO")
        if isinstance(data, dict):
            data = data.get("estrategias")
        if not isinstance(data, list):
            raise Unprocessable("El JSON debe ser una lista de estrategias o un objeto con la clave «estrategias».",
                                "JSON_INVALIDO")
        filas = []
        for i, item in enumerate(data, start=1):
            filas.append((i, item if isinstance(item, dict) else {}))
        return filas
    headers, rows = read_csv_rows(content)
    faltan = [c for c in ("codigo", "nombre", "descripcion_pedagogica", "principio", "pauta") if c not in headers]
    if faltan:
        raise Unprocessable("Al archivo le faltan columnas obligatorias: " + ", ".join(faltan) + ".",
                            "CSV_COLUMNAS_FALTANTES")
    return rows


def import_catalog(
    db: Session, actor: Usuario, content: bytes, filename: str | None, content_type: str | None, *,
    dry_run: bool = True, actualizar_existentes: bool = False, omitir_errores: bool = False, request=None,
) -> dict[str, Any]:
    filas = parse_upload(content, filename, content_type)
    if not filas:
        raise Unprocessable("El archivo no trae estrategias.", "CSV_VACIO")
    if len(filas) > MAX_FILAS:
        raise AppError(f"El archivo tiene {len(filas)} filas; el máximo por carga es {MAX_FILAS}.", "CSV_DEMASIADAS_FILAS",
                       status_code=422)
    existentes = {e.codigo: e for e in db.scalars(select(EstrategiaDuaCatalogo))}
    vistos: dict[str, int] = {}
    errores: list[dict[str, Any]] = []
    plan: list[tuple[str, dict[str, Any], EstrategiaDuaCatalogo | None]] = []
    for pos, raw in filas:
        d, errs = normalize_row(raw)
        if d["codigo"] and d["codigo"] in vistos:
            errs.append(("codigo", f"El código {d['codigo']} ya aparece en la fila {vistos[d['codigo']]}."))
        elif d["codigo"]:
            vistos[d["codigo"]] = pos
        if errs:
            for campo, msg in errs:
                errores.append({"fila": pos, "campo": campo, "mensaje": msg})
            continue
        ex = existentes.get(d["codigo"])
        if ex is None:
            plan.append(("NUEVA", d, None))
        elif actualizar_existentes:
            plan.append(("ACTUALIZADA", d, ex))
        else:
            plan.append(("EXISTENTE", d, ex))
    resumen = {
        "dry_run": dry_run, "total_filas": len(filas),
        "nuevas": sum(1 for t, _, _ in plan if t == "NUEVA"),
        "actualizadas": sum(1 for t, _, _ in plan if t == "ACTUALIZADA"),
        "existentes_omitidas": sum(1 for t, _, _ in plan if t == "EXISTENTE"),
        "con_errores": len({e["fila"] for e in errores}), "errores": errores, "creadas": 0, "modificadas": 0,
    }
    if dry_run:
        return resumen
    if errores and not omitir_errores:
        raise AppError(
            f"El archivo tiene {resumen['con_errores']} fila(s) con errores y no se importó nada. Corríjalas o use "
            "«omitir filas con error».", "CSV_CON_ERRORES", status_code=422,
            extra={"errores": errores, "total_filas": len(filas), "con_errores": resumen["con_errores"]},
        )
    for tipo, d, ex in plan:
        if tipo == "NUEVA":
            db.add(EstrategiaDuaCatalogo(**d))
            resumen["creadas"] += 1
        elif tipo == "ACTUALIZADA" and ex is not None:
            for k, v in d.items():
                setattr(ex, k, v)
            resumen["modificadas"] += 1
    db.flush()
    audit.log(db, actor, "CATALOGO_DUA_IMPORTADO", "estrategia_dua_catalogo", None,
              {"archivo": filename, "creadas": resumen["creadas"], "modificadas": resumen["modificadas"],
               "omitidas": resumen["existentes_omitidas"], "con_errores": resumen["con_errores"]}, request=request)
    return resumen


def export_csv(rows: list[EstrategiaDuaCatalogo]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CAMPOS)
    for e in rows:
        w.writerow([
            e.codigo, e.nombre, e.descripcion_pedagogica, str(e.principio), e.pauta, e.pauta_nombre or "",
            e.punto_verificacion or "", "|".join(e.escenarios or []), "|".join(e.tipos_barrera or []),
            e.perfil_estudiante or "", e.fuente or "", "1" if e.activo else "0",
        ])
    return "﻿" + buf.getvalue()


def export_json(rows: list[EstrategiaDuaCatalogo]) -> str:
    data = []
    for e in rows:
        s = serialize(e)
        data.append({k: s[k] for k in CAMPOS})
    return json.dumps({"estrategias": data}, ensure_ascii=False, indent=2)
