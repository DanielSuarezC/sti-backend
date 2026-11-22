"""Importación CSV de estudiantes (Vía 3, RF-04, HU-04) y utilidades de lectura de CSV compartidas.

Formato del CSV de estudiantes (UTF-8 o Latin-1; separador coma o punto y coma; primera fila = encabezados;
las líneas que empiezan con `#` se ignoran):

    nombre_completo,codigo_estudiante,correo_institucional,programa[,telefono][,semestre_actual][,anio_ingreso]

* `programa`: código (`ENF`) o nombre exacto (`Enfermería`) de un programa ya creado.
* Encabezados aceptados con sinónimos (`nombre`, `codigo`, `correo`, `email`, `programa_academico`...), sin distinguir
  mayúsculas ni tildes.
* Máximo 1000 filas y 2 MB por archivo.

Reglas: la importación es IDEMPOTENTE (mismo código + mismo correo = «YA_EXISTE», se omite sin error);
código o correo en conflicto con otra cuenta = error de esa fila. `dry_run=true` valida sin escribir nada.
Las cuentas nuevas quedan en PENDIENTE_CONSENTIMIENTO y reciben un correo explicativo con el enlace al F0.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import AppError, Unprocessable
from app.models.academico import ProgramaAcademico
from app.models.enums import EstadoUsuario, ViaIngreso
from app.models.usuarios import Estudiante, Usuario
from app.services.accounts import normalize_email
from app.services.directorio import email_dominio_permitido, mensaje_dominio
from app.services.student_intake import create_student_account, send_via3_email

MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 1000
ENCABEZADOS = ["nombre_completo", "codigo_estudiante", "correo_institucional", "programa"]
OPCIONALES = ["telefono", "semestre_actual", "anio_ingreso"]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_ALIAS = {
    "nombre_completo": {"nombre_completo", "nombre", "nombres", "nombre_y_apellidos", "estudiante"},
    "codigo_estudiante": {"codigo_estudiante", "codigo", "codigo_estudiantil", "cod_estudiante", "codigo_del_estudiante"},
    "correo_institucional": {"correo_institucional", "correo", "email", "e_mail", "correo_electronico", "email_institucional"},
    "programa": {"programa", "programa_academico", "codigo_programa", "nombre_programa", "carrera"},
    "telefono": {"telefono", "celular", "tel"},
    "semestre_actual": {"semestre_actual", "semestre"},
    "anio_ingreso": {"anio_ingreso", "ano_ingreso", "anio", "ano"},
}


def _norm(txt: str) -> str:
    t = unicodedata.normalize("NFKD", txt.strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def decode_bytes(content: bytes) -> str:
    if len(content) > MAX_BYTES:
        raise AppError("El archivo es demasiado grande (máximo 2 MB).", "ARCHIVO_MUY_GRANDE", status_code=413)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise Unprocessable("No pudimos leer el archivo. Guárdelo como CSV UTF-8.", "CSV_ILEGIBLE")


def read_csv_rows(content: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Devuelve (encabezados normalizados, [(numero_de_fila, fila)]). La fila 1 es el encabezado."""
    text = decode_bytes(content)
    lines = [(i, ln) for i, ln in enumerate(text.splitlines(), start=1) if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise Unprocessable("El archivo está vacío. Descargue la plantilla y complétela.", "CSV_VACIO")
    primera = lines[0][1]
    delim = ";" if primera.count(";") > primera.count(",") else ","
    reader = csv.reader(io.StringIO("\n".join(ln for _, ln in lines)), delimiter=delim)
    filas = list(reader)
    headers = [_norm(h) for h in filas[0]]
    rows: list[tuple[int, dict[str, str]]] = []
    for (num, _), valores in zip(lines[1:], filas[1:], strict=False):
        if not any(v.strip() for v in valores):
            continue
        rows.append((num, {h: (valores[i].strip() if i < len(valores) else "") for i, h in enumerate(headers)}))
    return headers, rows


def read_excel_rows(content: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Lee filas de un archivo Excel (.xlsx). Devuelve (encabezados normalizados, [(num_fila, fila)])."""
    import openpyxl

    if len(content) > MAX_BYTES:
        raise AppError("El archivo es demasiado grande (máximo 2 MB).", "ARCHIVO_MUY_GRANDE", status_code=413)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        sheet = wb.active
    except Exception as exc:
        raise Unprocessable(f"No pudimos leer el archivo Excel (.xlsx): {exc}", "EXCEL_ILEGIBLE")

    rows_iter = list(sheet.iter_rows(values_only=True))
    if not rows_iter:
        raise Unprocessable("El archivo Excel está vacío. Descargue la plantilla y complétela.", "EXCEL_VACIO")

    # Encontrar la fila de encabezados (primera fila no vacía que no empiece con #)
    header_idx = None
    for idx, row in enumerate(rows_iter):
        non_empty = [c for c in row if c is not None and str(c).strip()]
        if non_empty:
            first_val = str(non_empty[0]).strip()
            if first_val.startswith("#"):
                continue
            header_idx = idx
            break

    if header_idx is None:
        raise Unprocessable("El archivo Excel no tiene encabezados válidos.", "EXCEL_VACIO")

    header_row = rows_iter[header_idx]
    headers = [_norm(str(h or "")) for h in header_row if h is not None and str(h).strip()]

    rows: list[tuple[int, dict[str, str]]] = []
    for num, row in enumerate(rows_iter[header_idx + 1:], start=header_idx + 2):
        if not any(c is not None and str(c).strip() for c in row):
            continue
        vals = [str(c).strip() if c is not None else "" for c in row]
        row_dict = {headers[i]: (vals[i] if i < len(vals) else "") for i in range(min(len(headers), len(vals)))}
        # Rellenar encabezados faltantes con vacío
        for h in headers:
            row_dict.setdefault(h, "")
        rows.append((num, row_dict))

    return headers, rows


def read_any_rows(content: bytes, filename: str | None = None) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Detecta automáticamente si el archivo es Excel (.xlsx) o CSV y lo procesa."""
    es_excel = (filename and filename.lower().endswith(".xlsx")) or content.startswith(b"PK\x03\x04")
    if es_excel:
        return read_excel_rows(content)
    return read_csv_rows(content)


def plantilla_csv() -> str:
    return (
        "# Plantilla de importación de estudiantes (Vía 3). Elimine estas líneas que empiezan con # antes de cargar.\n"
        "# programa: código (p. ej. ENF) o nombre exacto del programa. Separador: coma o punto y coma.\n"
        "# Columnas opcionales al final: telefono, semestre_actual, anio_ingreso.\n"
        + ",".join(ENCABEZADOS + OPCIONALES) + "\n"
    )


def plantilla_xlsx() -> bytes:
    """Genera una plantilla Excel (.xlsx) con estilos, columnas y fila de ejemplo."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estudiantes"

    headers = ENCABEZADOS + OPCIONALES
    ws.append(headers)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB"),
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Fila de ejemplo
    ejemplo = [
        "María Camila Restrepo Pérez",
        "2026102045",
        "mcrestrepo@correo.unicordoba.edu.co",
        "ENF",
        "3001234567",
        1,
        2026,
    ]
    ws.append(ejemplo)
    for col_idx in range(1, len(ejemplo) + 1):
        cell = ws.cell(row=2, column=col_idx)
        cell.border = thin_border

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 16)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _resolver_columnas(headers: list[str]) -> dict[str, str]:
    """campo canónico -> encabezado real del archivo."""
    mapa: dict[str, str] = {}
    for canon, alias in _ALIAS.items():
        for h in headers:
            if h in alias and canon not in mapa:
                mapa[canon] = h
    faltan = [c for c in ENCABEZADOS if c not in mapa]
    if faltan:
        raise Unprocessable(
            "Al archivo le faltan columnas obligatorias: " + ", ".join(faltan) + ". Descargue la plantilla.",
            "CSV_COLUMNAS_FALTANTES",
        )
    return mapa


def _to_int(valor: str, campo: str, minimo: int, maximo: int) -> tuple[int | None, str | None]:
    if not valor:
        return None, None
    try:
        n = int(valor)
    except ValueError:
        return None, f"{campo} debe ser un número entero."
    if not minimo <= n <= maximo:
        return None, f"{campo} debe estar entre {minimo} y {maximo}."
    return n, None


def analyze_students(db: Session, content: bytes, filename: str | None = None) -> dict[str, Any]:
    """Valida todas las filas sin escribir. Devuelve filas analizadas + errores + conteos."""
    headers, rows = read_any_rows(content, filename)
    cols = _resolver_columnas(headers)
    if len(rows) > MAX_FILAS:
        raise AppError(f"El archivo tiene {len(rows)} filas; el máximo por carga es {MAX_FILAS}.", "CSV_DEMASIADAS_FILAS",
                       status_code=422)
    if not rows:
        raise Unprocessable("El archivo no tiene filas de estudiantes debajo de los encabezados.", "CSV_VACIO")

    progs = list(db.scalars(select(ProgramaAcademico)))
    por_codigo = {p.codigo_programa.strip().lower(): p for p in progs}
    por_nombre = {p.nombre_programa.strip().lower(): p for p in progs}
    por_nombre.update({_norm(p.nombre_programa): p for p in progs})

    vistos_codigo: dict[str, int] = {}
    vistos_correo: dict[str, int] = {}
    analizadas: list[dict[str, Any]] = []
    errores: list[dict[str, Any]] = []

    for num, fila in rows:
        datos = {canon: fila.get(h, "") for canon, h in cols.items()}
        g = datos.get

        item: dict[str, Any] = {
            "fila": num, "nombre_completo": g("nombre_completo", ""), "codigo_estudiante": g("codigo_estudiante", ""),
            "correo_institucional": normalize_email(g("correo_institucional", "")) if g("correo_institucional", "") else "",
            "programa": g("programa", ""), "telefono": g("telefono", "") or None, "estado": "NUEVO", "programa_id": None,
            "semestre_actual": None, "anio_ingreso": None,
        }
        errs: list[tuple[str, str]] = []
        if not item["nombre_completo"]:
            errs.append(("nombre_completo", "El nombre completo es obligatorio."))
        elif len(item["nombre_completo"]) > 255:
            errs.append(("nombre_completo", "El nombre completo es demasiado largo (máximo 255)."))
        codigo = item["codigo_estudiante"]
        if not codigo:
            errs.append(("codigo_estudiante", "El código estudiantil es obligatorio."))
        elif len(codigo) > 50:
            errs.append(("codigo_estudiante", "El código estudiantil es demasiado largo (máximo 50)."))
        correo = item["correo_institucional"]
        if not correo:
            errs.append(("correo_institucional", "El correo institucional es obligatorio."))
        elif not _EMAIL_RE.match(correo):
            errs.append(("correo_institucional", f"«{correo}» no es un correo válido."))
        elif not email_dominio_permitido(correo):
            errs.append(("correo_institucional", f"«{correo}» no es institucional. {mensaje_dominio()}"))
        prog_txt = item["programa"]
        prog = por_codigo.get(prog_txt.lower()) or por_nombre.get(prog_txt.lower()) or por_nombre.get(_norm(prog_txt)) if prog_txt else None
        if not prog_txt:
            errs.append(("programa", "El programa es obligatorio."))
        elif prog is None:
            errs.append(("programa", f"El programa «{prog_txt}» no existe. Use el código o el nombre exacto."))
        else:
            item["programa_id"] = prog.id
        sem, e1 = _to_int(g("semestre_actual", ""), "semestre_actual", 1, 20)
        anio, e2 = _to_int(g("anio_ingreso", ""), "anio_ingreso", 1990, date.today().year + 1)
        for e in (e1, e2):
            if e:
                errs.append((e.split()[0], e))
        item["semestre_actual"], item["anio_ingreso"] = sem, anio

        # duplicados dentro del archivo
        if codigo and codigo in vistos_codigo:
            errs.append(("codigo_estudiante", f"El código {codigo} ya aparece en la fila {vistos_codigo[codigo]}."))
        elif codigo:
            vistos_codigo[codigo] = num
        if correo and correo in vistos_correo:
            errs.append(("correo_institucional", f"El correo {correo} ya aparece en la fila {vistos_correo[correo]}."))
        elif correo:
            vistos_correo[correo] = num

        # contra la base de datos (idempotencia)
        if not errs:
            est = db.scalar(select(Estudiante).where(Estudiante.codigo_estudiante == codigo)
                            .execution_options(include_deleted=True))
            usr = db.scalar(select(Usuario).where(Usuario.email == correo).execution_options(include_deleted=True))
            if est is not None:
                dueno = db.get(Usuario, est.usuario_id)
                if dueno is not None and dueno.email == correo:
                    item["estado"] = "YA_EXISTE"
                else:
                    errs.append(("codigo_estudiante", f"El código {codigo} ya está registrado con otro correo."))
            elif usr is not None:
                errs.append(("correo_institucional", f"El correo {correo} ya pertenece a otra cuenta."))
        if errs:
            item["estado"] = "ERROR"
            for campo, msg in errs:
                errores.append({"fila": num, "campo": campo, "mensaje": msg})
        analizadas.append(item)

    return {
        "filas": analizadas, "errores": errores,
        "total_filas": len(analizadas),
        "nuevas": sum(1 for f in analizadas if f["estado"] == "NUEVO"),
        "ya_existentes": sum(1 for f in analizadas if f["estado"] == "YA_EXISTE"),
        "con_errores": len({e["fila"] for e in errores}),
    }


def import_students(
    db: Session, actor: Usuario, content: bytes, *, dry_run: bool = True, omitir_errores: bool = False,
    nombre_archivo: str | None = None, request=None, hoy: date | None = None,
) -> dict[str, Any]:
    """Vía 3. Con `dry_run` no escribe nada. Sin commit (lo hace el router)."""
    an = analyze_students(db, content, filename=nombre_archivo)
    base = {
        "dry_run": dry_run, "total_filas": an["total_filas"], "validas": an["nuevas"] + an["ya_existentes"],
        "nuevas": an["nuevas"], "ya_existentes": an["ya_existentes"], "con_errores": an["con_errores"],
        "errores": an["errores"], "creados": 0, "omitidos": an["ya_existentes"], "omitidos_por_error": 0,
    }
    if dry_run:
        return base
    if an["errores"] and not omitir_errores:
        raise AppError(
            f"El archivo tiene {an['con_errores']} fila(s) con errores y no se importó nada. Corríjalas o use "
            "«omitir filas con error».", "CSV_CON_ERRORES", status_code=422,
            extra={"errores": an["errores"], "total_filas": an["total_filas"], "con_errores": an["con_errores"]},
        )
    creados = 0
    for f in an["filas"]:
        if f["estado"] != "NUEVO":
            continue
        try:
            with db.begin_nested():
                user, _est = create_student_account(
                    db, nombre_completo=f["nombre_completo"], email=f["correo_institucional"],
                    codigo=f["codigo_estudiante"], programa_id=f["programa_id"], via=ViaIngreso.MATRICULA_CSV,
                    estado=EstadoUsuario.PENDIENTE_CONSENTIMIENTO, telefono=f["telefono"],
                    anio_ingreso=f["anio_ingreso"], semestre_actual=f["semestre_actual"], crear_matricula=True, hoy=hoy,
                )
                send_via3_email(db, user, actor=actor)
            creados += 1
        except Exception as exc:  # noqa: BLE001 - la fila falla sola; el resto sigue
            base["errores"].append({"fila": f["fila"], "campo": "fila", "mensaje": f"No se pudo crear la cuenta: {str(exc)[:160]}"})
            base["omitidos_por_error"] += 1
    base["creados"] = creados
    audit.log(db, actor, "IMPORTACION_CSV_ESTUDIANTES", "usuario", None,
              {"archivo": nombre_archivo, "filas": an["total_filas"], "creados": creados,
               "ya_existentes": an["ya_existentes"], "con_errores": an["con_errores"]}, request=request)
    return base
