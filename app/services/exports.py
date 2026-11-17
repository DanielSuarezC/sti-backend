"""Exportación del Plan MAAR-TEA a PDF (WeasyPrint), Word (python-docx) y HTML imprimible (RF-27, RNF-03).

* PDF con firma digital VISIBLE: nombres, fecha/hora (Colombia), hash corto y estado de verificación (recalculado).
* Si `import weasyprint` falla (p. ej. Windows sin GTK) el PDF se degrada a HTML imprimible (`formato=html`) y la respuesta
  lo avisa; nunca un 500.
* La exportación es asíncrona: `EXPORTACION` (SOLICITADA) -> tarea (`tasks.enqueue`) -> LISTA/ERROR; el archivo vive en
  `services.storage`; se notifica (EXPORTACION_LISTA) y expira (`expire_exports`).
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from string import Template

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import session_scope
from app.models.base import utcnow
from app.models.enums import EstadoExportacion, TipoAjuste, TipoExportacion
from app.models.plan import PlanMaarTea
from app.models.sistema import Exportacion
from app.models.usuarios import Usuario
from app.services import plan_builder as builder
from app.services import plan_common as common
from app.services import plan_signatures as sig
from app.services import plan_views as views
from app.services import storage
from app.services.notifications import Evento
from app.services.params import get_param
from app.services.tasks import enqueue, task

logger = logging.getLogger("sti.exports")

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
BOGOTA = timezone(timedelta(hours=-5))  # Colombia no tiene horario de verano
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ORDEN_CATEGORIAS = [t.value for t in TipoAjuste]
ETIQUETA_ROL = {"ESTUDIANTE": "Estudiante", "BIENESTAR": "Profesional de Bienestar", "COORDINADOR": "Coordinador de programa"}


def pdf_disponible() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - OSError por falta de GTK/Pango es el caso típico en Windows
        return False


# ----------------------------------------------------------------------------- contexto del documento
def _fecha_hora(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(BOGOTA).strftime("%d/%m/%Y %H:%M") + " (hora de Colombia)"


def _f(d) -> str:
    if not d:
        return "—"
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d/%m/%Y")


def contexto(db: Session, plan: PlanMaarTea) -> dict:
    """Datos del documento. Usa la vista COMPLETA del plan (el rol que exporta ya fue autorizado)."""
    est = common.estudiante_de(db, plan)
    vista = views.serializar_plan(db, plan, _SistemaVista(db, plan))
    verif = sig.verificar(db, plan)
    firmas_vig = {f["rol_firmante"]: f for f in vista["firmas"] if f["estado"] == "FIRMADA"}
    filas_firma = []
    for rol in sig.orden_firmas(db):
        f = firmas_vig.get(rol)
        det = next((x for v in verif["versiones"] if v["version"] == plan.version for x in v["firmas"] if x["rol_firmante"] == rol
                    and x["estado"] == "FIRMADA"), None)
        filas_firma.append({
            "rol": ETIQUETA_ROL.get(rol, rol), "nombre": (f["firmante"] or {}).get("nombre_completo") if f else None,
            "fecha": f["firmado_at"] if f else None, "hash_corto": f["hash_corto"] if f else None,
            "estado": ("Firma válida" if det and det["valida"] else "Firma no verificable") if f else "Pendiente de firma",
        })
    matriz = builder.matriz_de(db, plan) if builder.tiene_matriz(db, plan.id) else None
    return {"plan": plan, "est": est, "vista": vista, "verif": verif, "firmas": filas_firma, "matriz": matriz,
            "generado": utcnow(), "hash_contenido": vista["hash_contenido"]}


class _SistemaVista:
    """Usuario ficticio con rol BIENESTAR para reutilizar la vista completa al exportar (sin acciones del usuario real)."""

    def __init__(self, db: Session, plan: PlanMaarTea):
        self.id = -1
        self.rol = "BIENESTAR"
        self.estado = "ACTIVO"


# ----------------------------------------------------------------------------- HTML
def _td(valor) -> str:
    return f"<td>{escape(str(valor)) if valor not in (None, '') else '—'}</td>"


def _sem(a: dict) -> str:
    s = a.get("semaforo")
    if not s:
        return "<td>Sin registro de seguimiento</td>"
    return f'<td><span class="sem sem-{s["valor"]}">{escape(s["texto"])}</span></td>'


def _tabla_ajustes(ajustes: list[dict]) -> str:
    filas = []
    for a in ajustes:
        det = a["detalle"] or {}
        quien = (a["responsable"] or {}).get("nombre_completo")
        barrera = a["barrera"] or {}
        fort = (a.get("fortaleza") or {}).get("nombre_fortaleza")
        recurso = " · ".join(x for x in (a["recurso"], a["frecuencia"]) if x) or None
        fechas = f"{_f(a['fecha_inicio'])} a {_f(a['fecha_fin_prevista']) if a['fecha_fin_prevista'] else 'sin fecha de fin'}"
        que = f"<strong>{escape(a['nombre_ajuste'])}</strong><br>{escape(a['descripcion_ajuste'])}"
        if det.get("tipo"):
            que += f"<br><em>Tipo: {escape(det['tipo'].replace('_', ' ').lower())}</em>"
        bar = f"{escape(str(barrera.get('tipo_barrera', '—')).lower())}: {escape(barrera.get('descripcion_barrera') or '')}"
        filas.append(
            f"<tr><td>{que}</td><td>{bar}</td>{_td(fort)}{_td(quien)}{_td(recurso)}{_td(a['indicador_efectividad'])}"
            f"{_td(fechas)}{_td(a['estado'].replace('_', ' ').lower())}{_sem(a)}</tr>")
    cab = ("<tr><th scope='col'>Ajuste</th><th scope='col'>Barrera que resuelve</th><th scope='col'>Fortaleza en que se apoya</th>"
           "<th scope='col'>Responsable</th><th scope='col'>Recurso y frecuencia</th><th scope='col'>Indicador de efectividad</th>"
           "<th scope='col'>Fechas</th><th scope='col'>Estado</th><th scope='col'>Semáforo</th></tr>")
    return f"<table>{cab}{''.join(filas)}</table>"


def render_html(ctx: dict) -> str:
    plan, est, v = ctx["plan"], ctx["est"], ctx["vista"]
    nombre = v["estudiante"]["nombre_completo"]
    partes: list[str] = []
    partes.append(
        "<section aria-labelledby='datos'><h2 id='datos'>Datos del plan</h2><dl class='datos'>"
        f"<dt>Estudiante</dt><dd>{escape(nombre or '')}</dd>"
        f"<dt>Código</dt><dd>{escape(est.codigo_estudiante)}</dd>"
        f"<dt>Programa</dt><dd>{escape(v['estudiante']['programa'] or '—')}</dd>"
        f"<dt>Semestre</dt><dd>{escape(plan.semestre_academico)}</dd>"
        f"<dt>Versión</dt><dd>{plan.version}</dd>"
        f"<dt>Estado</dt><dd>{escape(str(plan.estado).replace('_', ' ').lower())}</dd>"
        f"<dt>Vigencia</dt><dd>{_f(plan.vigencia_inicio)} a {_f(plan.vigencia_fin) if plan.vigencia_fin else 'sin fecha de fin'}</dd>"
        f"<dt>Elaborado por</dt><dd>{escape((v['elaborado_por'] or {}).get('nombre_completo') or '—')}</dd>"
        f"<dt>Validado por</dt><dd>{escape((v['validado_por'] or {}).get('nombre_completo') or 'Pendiente')}</dd>"
        "</dl></section>")
    if str(plan.estado) not in ("APROBADO", "IMPLEMENTACION", "SEGUIMIENTO", "FINALIZADO"):
        partes.append("<p class='aviso'><strong>Borrador sin firmas completas:</strong> este documento aún no tiene validez; "
                      "falta concertación, validación o firma.</p>")
    if plan.resumen_ejecutivo or plan.justificacion_apoyos:
        partes.append("<section><h2>Resumen</h2>")
        if plan.resumen_ejecutivo:
            partes.append(f"<p>{escape(plan.resumen_ejecutivo)}</p>")
        if plan.justificacion_apoyos:
            partes.append(f"<h3>Justificación de los apoyos</h3><p>{escape(plan.justificacion_apoyos)}</p>")
        partes.append("</section>")
    # estrategias DUA
    partes.append("<section><h2>Estrategias DUA (medidas universales)</h2>")
    if v["estrategias_dua"]:
        filas = "".join(
            f"<tr><td><strong>{escape(e['nombre_estrategia'])}</strong><br>{escape(e['descripcion'])}</td>"
            f"{_td(e['dimension_dua'].replace('MULTIPLES_MEDIOS_', 'Múltiples medios de ').replace('_', ' ').lower())}"
            f"{_td((e['responsable'] or {}).get('nombre_completo'))}{_td(e['alcance'])}</tr>" for e in v["estrategias_dua"])
        partes.append("<table><tr><th scope='col'>Estrategia</th><th scope='col'>Dimensión DUA</th>"
                      f"<th scope='col'>Responsable</th><th scope='col'>Alcance</th></tr>{filas}</table>")
    else:
        partes.append("<p>El plan no incluye estrategias DUA.</p>")
    partes.append("</section>")
    # ajustes por categoría
    partes.append("<section><h2>Ajustes razonables por categoría</h2>")
    if not v["ajustes"]:
        partes.append("<p>El plan no incluye ajustes razonables.</p>")
    for cat in ORDEN_CATEGORIAS:
        grupo = [a for a in v["ajustes"] if a["tipo_ajuste"] == cat]
        if grupo:
            partes.append(f"<h3>{escape(grupo[0]['categoria'])}</h3>{_tabla_ajustes(grupo)}")
    partes.append("</section>")
    # matriz F7
    m = ctx["matriz"]
    if m:
        cortes = ", ".join(f"{c['corte']}: {_f(c['fecha'])}" for c in (m["calendario"] or {}).get("cortes", []))
        filas = "".join(
            f"<tr>{_td(ap['nombre_apoyo'])}{_td(((ap['responsable_principal'] or {}).get('usuario') or {}).get('nombre_completo'))}"
            f"{_td(((ap['responsable_secundario'] or {}).get('usuario') or {}).get('nombre_completo'))}"
            f"{_td((ap['recurso'] or {}).get('descripcion_recurso'))}{_td(ap['frecuencia'])}"
            f"{_td(_f(ap['fecha_inicio']) + ' a ' + _f(ap['fecha_fin_prevista']))}</tr>" for ap in m["apoyos"])
        partes.append(f"<section><h2>Matriz de responsabilidades (F7)</h2><p>Cortes del semestre: {escape(cortes or '—')}</p>"
                      "<table><tr><th scope='col'>Apoyo</th><th scope='col'>Responsable principal</th>"
                      "<th scope='col'>Responsable secundario</th><th scope='col'>Recurso</th><th scope='col'>Frecuencia</th>"
                      f"<th scope='col'>Fechas</th></tr>{filas}</table></section>")
    # firmas visibles
    filas = "".join(
        f"<tr>{_td(f['rol'])}{_td(f['nombre'] or 'Pendiente')}{_td(_fecha_hora(datetime.fromisoformat(f['fecha'])) if f['fecha'] else '—')}"
        f"<td class='hash'>{escape(f['hash_corto'] or '—')}</td>{_td(f['estado'])}</tr>" for f in ctx["firmas"])
    verif = ctx["verif"]
    if verif["completo"]:
        caja = "<p class='ok'><strong>Verificación:</strong> las tres firmas son válidas y el contenido del plan coincide con lo firmado.</p>"
    elif verif["firmas_vigentes"] and not verif["integro"]:
        caja = "<p class='mal'><strong>Verificación fallida:</strong> el contenido del plan no coincide con el hash firmado.</p>"
    else:
        caja = "<p class='aviso'><strong>Verificación:</strong> el plan aún no tiene las tres firmas vigentes.</p>"
    partes.append(
        "<section><h2>Firmas digitales</h2>"
        "<table><tr><th scope='col'>Rol</th><th scope='col'>Nombre</th><th scope='col'>Fecha y hora de la firma</th>"
        f"<th scope='col'>Hash de firma (corto)</th><th scope='col'>Estado</th></tr>{filas}</table>{caja}"
        f"<p>Huella SHA-256 del contenido (versión {plan.version}): <span class='hash'>{escape(ctx['hash_contenido'])}</span></p>"
        "</section>")
    css = (TEMPLATES / "plan_maar_tea.css").read_text(encoding="utf-8")
    base = Template((TEMPLATES / "plan_maar_tea.html").read_text(encoding="utf-8"))
    return base.safe_substitute(
        titulo=escape(f"Plan MAAR-TEA — {nombre} — {plan.semestre_academico} (v{plan.version})"), css=css,
        cuerpo="\n".join(partes), generado=_fecha_hora(ctx["generado"]),
        nota_html="Este plan se construyó de forma concertada con la persona estudiante y puede ajustarse cuando lo necesite.")


# ----------------------------------------------------------------------------- PDF y Word
def render_pdf(html: str) -> bytes:
    import weasyprint

    return weasyprint.HTML(string=html).write_pdf()


def render_docx(ctx: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt

    plan, est, v = ctx["plan"], ctx["est"], ctx["vista"]
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.core_properties.title = f"Plan MAAR-TEA — {v['estudiante']['nombre_completo']}"
    doc.core_properties.language = "es-CO"
    doc.add_heading("Plan MAAR-TEA", level=0)
    doc.add_paragraph("Modelo Institucional de Apoyos y Ajustes Razonables para estudiantes con TEA · Universidad de Córdoba · STI")
    doc.add_heading("Datos del plan", level=1)
    datos = [("Estudiante", v["estudiante"]["nombre_completo"]), ("Código", est.codigo_estudiante),
             ("Programa", v["estudiante"]["programa"] or "—"), ("Semestre", plan.semestre_academico),
             ("Versión", str(plan.version)), ("Estado", str(plan.estado).replace("_", " ").lower()),
             ("Vigencia", f"{_f(plan.vigencia_inicio)} a {_f(plan.vigencia_fin) if plan.vigencia_fin else 'sin fecha de fin'}"),
             ("Elaborado por", (v["elaborado_por"] or {}).get("nombre_completo") or "—"),
             ("Validado por", (v["validado_por"] or {}).get("nombre_completo") or "Pendiente")]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, val in datos:
        r = t.add_row().cells
        r[0].text, r[1].text = k, str(val)
    if str(plan.estado) not in ("APROBADO", "IMPLEMENTACION", "SEGUIMIENTO", "FINALIZADO"):
        doc.add_paragraph("Borrador sin firmas completas: este documento aún no tiene validez.").runs[0].bold = True
    if plan.resumen_ejecutivo:
        doc.add_heading("Resumen", level=1)
        doc.add_paragraph(plan.resumen_ejecutivo)
    if plan.justificacion_apoyos:
        doc.add_heading("Justificación de los apoyos", level=2)
        doc.add_paragraph(plan.justificacion_apoyos)
    doc.add_heading("Estrategias DUA (medidas universales)", level=1)
    if not v["estrategias_dua"]:
        doc.add_paragraph("El plan no incluye estrategias DUA.")
    for e in v["estrategias_dua"]:
        doc.add_paragraph(f"{e['nombre_estrategia']}: {e['descripcion']}", style="List Bullet")
    doc.add_heading("Ajustes razonables por categoría", level=1)
    if not v["ajustes"]:
        doc.add_paragraph("El plan no incluye ajustes razonables.")
    for cat in ORDEN_CATEGORIAS:
        grupo = [a for a in v["ajustes"] if a["tipo_ajuste"] == cat]
        if not grupo:
            continue
        doc.add_heading(grupo[0]["categoria"], level=2)
        tabla = doc.add_table(rows=1, cols=7)
        tabla.style = "Table Grid"
        for i, h in enumerate(("Ajuste", "Barrera que resuelve", "Fortaleza", "Responsable", "Recurso y frecuencia",
                               "Indicador de efectividad", "Semáforo")):
            tabla.rows[0].cells[i].text = h
            for run in tabla.rows[0].cells[i].paragraphs[0].runs:
                run.bold = True
        for a in grupo:
            c = tabla.add_row().cells
            b = a["barrera"] or {}
            c[0].text = f"{a['nombre_ajuste']}\n{a['descripcion_ajuste']}"
            c[1].text = f"{str(b.get('tipo_barrera', '')).lower()}: {b.get('descripcion_barrera') or ''}"
            c[2].text = (a.get("fortaleza") or {}).get("nombre_fortaleza") or "—"
            c[3].text = (a["responsable"] or {}).get("nombre_completo") or "—"
            c[4].text = " · ".join(x for x in (a["recurso"], a["frecuencia"]) if x) or "—"
            c[5].text = a["indicador_efectividad"] or "—"
            c[6].text = a["semaforo"]["texto"] if a["semaforo"] else "Sin registro de seguimiento"
    m = ctx["matriz"]
    if m:
        doc.add_heading("Matriz de responsabilidades (F7)", level=1)
        doc.add_paragraph("Cortes del semestre: " + ", ".join(f"{c['corte']}: {_f(c['fecha'])}" for c in (m["calendario"] or {}).get("cortes", [])))
        tabla = doc.add_table(rows=1, cols=5)
        tabla.style = "Table Grid"
        for i, h in enumerate(("Apoyo", "Responsable principal", "Responsable secundario", "Recurso", "Fechas")):
            tabla.rows[0].cells[i].text = h
        for ap in m["apoyos"]:
            c = tabla.add_row().cells
            c[0].text = ap["nombre_apoyo"]
            c[1].text = ((ap["responsable_principal"] or {}).get("usuario") or {}).get("nombre_completo") or "—"
            c[2].text = ((ap["responsable_secundario"] or {}).get("usuario") or {}).get("nombre_completo") or "—"
            c[3].text = (ap["recurso"] or {}).get("descripcion_recurso") or "—"
            c[4].text = f"{_f(ap['fecha_inicio'])} a {_f(ap['fecha_fin_prevista'])}"
    doc.add_heading("Firmas digitales", level=1)
    tabla = doc.add_table(rows=1, cols=5)
    tabla.style = "Table Grid"
    for i, h in enumerate(("Rol", "Nombre", "Fecha y hora", "Hash de firma (corto)", "Estado")):
        tabla.rows[0].cells[i].text = h
    for f in ctx["firmas"]:
        c = tabla.add_row().cells
        c[0].text, c[1].text = f["rol"], f["nombre"] or "Pendiente"
        c[2].text = _fecha_hora(datetime.fromisoformat(f["fecha"])) if f["fecha"] else "—"
        c[3].text, c[4].text = f["hash_corto"] or "—", f["estado"]
    verif = ctx["verif"]
    doc.add_paragraph("Verificación: " + ("las tres firmas son válidas y el contenido coincide con lo firmado." if verif["completo"]
                                          else "el plan aún no tiene las tres firmas vigentes válidas."))
    doc.add_paragraph(f"Huella SHA-256 del contenido (versión {plan.version}): {ctx['hash_contenido']}")
    doc.add_paragraph(f"Documento generado el {_fecha_hora(ctx['generado'])} por el STI.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- flujo asíncrono
def solicitar(db: Session, plan: PlanMaarTea, user: Usuario, formato: str, request: Request | None = None) -> Exportacion:
    """Crea la EXPORTACION (SOLICITADA). El router hace commit y luego llama a `encolar`."""
    formato = formato.lower()
    aviso = None
    efectivo = formato
    if formato == "pdf" and not pdf_disponible():
        efectivo = "html"
        aviso = ("El servidor no puede generar PDF en este momento; se generó una versión HTML imprimible "
                 "(imprímala o guárdela como PDF desde el navegador).")
    dias = int(get_param(db, "dias_expiracion_exportacion", 7))
    exp = Exportacion(
        solicitada_por_id=user.id, tipo=TipoExportacion.PLAN_DOCX if efectivo == "docx" else TipoExportacion.PLAN_PDF,
        estado=EstadoExportacion.SOLICITADA, plan_id=plan.id, estudiante_id=plan.estudiante_id,
        parametros={"formato": efectivo, "formato_solicitado": formato, "version": plan.version, "aviso": aviso},
        expira_at=utcnow() + timedelta(days=max(1, dias)),
    )
    db.add(exp)
    db.flush()
    audit.log(db, user, audit.Accion.EXPORTACION_SOLICITADA, "exportacion", exp.id,
              {"plan_id": plan.id, "formato": efectivo, "version": plan.version}, request=request, estudiante_id=plan.estudiante_id)
    return exp


def nombre_archivo(est_codigo: str, version: int, formato: str) -> str:
    return f"plan-maar-tea_{est_codigo}_v{version}_{date.today().isoformat()}.{formato}"


def construir_archivo(db: Session, plan: PlanMaarTea, formato: str) -> tuple[bytes, str]:
    ctx = contexto(db, plan)
    if formato == "docx":
        return render_docx(ctx), CONTENT_TYPES["docx"]
    html = render_html(ctx)
    if formato == "pdf":
        return render_pdf(html), CONTENT_TYPES["pdf"]
    return html.encode("utf-8"), CONTENT_TYPES["html"]


@task("generar_exportacion_task")
def generar_exportacion(exportacion_id: int) -> None:
    """Tarea: genera el archivo, lo guarda en almacenamiento y notifica. Nunca propaga errores."""
    from app.services.notifications import notify

    with session_scope() as db:
        exp = db.get(Exportacion, exportacion_id)
        if exp is None or exp.estado not in (EstadoExportacion.SOLICITADA, EstadoExportacion.PROCESANDO):
            return
        exp.estado = EstadoExportacion.PROCESANDO
        db.commit()
        try:
            plan = common.get_plan(db, exp.plan_id)
            formato = (exp.parametros or {}).get("formato", "pdf")
            try:
                data, ctype = construir_archivo(db, plan, formato)
            except Exception:  # noqa: BLE001 - el PDF falló en tiempo de ejecución: degradar a HTML
                if formato != "pdf":
                    raise
                logger.exception("Falló WeasyPrint; se degrada a HTML imprimible")
                formato = "html"
                data, ctype = construir_archivo(db, plan, "html")
                exp.parametros = {**(exp.parametros or {}), "formato": "html", "aviso":
                                  "No se pudo generar el PDF; se entrega HTML imprimible."}
            est = common.estudiante_de(db, plan)
            nombre = nombre_archivo(est.codigo_estudiante, plan.version, formato)
            key = storage.build_key("exportaciones", nombre)
            storage.put(key, data, ctype)
            exp.archivo_key, exp.archivo_nombre, exp.content_type = key, nombre, ctype
            exp.size_bytes = len(data)
            exp.estado = EstadoExportacion.LISTA
            exp.completada_at = utcnow()
            exp.error = None
            solicitante = db.get(Usuario, exp.solicitada_por_id)
            if solicitante is not None:
                notify(db, Evento.EXPORTACION_LISTA, [solicitante],
                       {"nombre_archivo": nombre, "exportacion_id": exp.id, "enlace": common.enlace_plan(str(solicitante.rol), plan)})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falló la exportación %s", exportacion_id)
            db.rollback()
            exp = db.get(Exportacion, exportacion_id)
            if exp is not None:
                exp.estado = EstadoExportacion.ERROR
                exp.error = f"{type(exc).__name__}: {exc}"[:900]
                db.commit()


def encolar(exportacion_id: int) -> str:
    return enqueue(generar_exportacion, exportacion_id)


def expire_exports(db: Session, hoy: date | None = None) -> int:
    """Marca como EXPIRADA y borra de almacenamiento las exportaciones vencidas (contrato de `services.jobs`)."""
    db.flush()
    ahora = utcnow()
    n = 0
    for e in db.scalars(select(Exportacion).where(Exportacion.estado == EstadoExportacion.LISTA,
                                                  Exportacion.expira_at.is_not(None), Exportacion.expira_at < ahora)):
        try:
            if e.archivo_key:
                storage.delete(e.archivo_key)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo borrar el archivo expirado %s", e.archivo_key)
        e.estado = EstadoExportacion.EXPIRADA
        n += 1
    return n
