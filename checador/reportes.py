"""Reportes en PDF y Excel.

- empleado:     asistencia de un empleado (o varios) en un mes o un rango de fechas
- historial:    lo mismo, más foto grande, datos personales, documentos y resumen por mes
- general:      todos los empleados en formato del reloj (checadas por día) y al final un resumen por persona
- incidencias:  solo faltas, retardos, salidas antes de tiempo y checadas incompletas
- directorio:   lista de empleados con foto y datos de contacto
- checadas:     formato del reloj: cada checada en su columna, horas, retardo, T.E. y falta por día
"""
import calendar
import io
import os
from collections import OrderedDict
from datetime import date, datetime, timedelta

from fpdf import FPDF

import asistencia
import db

AZUL = (37, 99, 235)
AZUL_CLARO = (239, 244, 255)
TINTA = (15, 23, 42)
GRIS = (100, 116, 139)
LINEA = (226, 232, 240)
ROJO = (200, 30, 30)
AMBAR = (180, 83, 9)
VERDE = (21, 128, 61)
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
FUENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fuentes")


# ---------------------------------------------------------------- periodos
def periodo(tipo, mes="", desde="", hasta=""):
    """Convierte lo elegido en pantalla (un mes completo o un rango de fechas) en (desde, hasta, etiqueta)."""
    if tipo == "fechas":
        try:
            d1 = datetime.strptime(desde, "%Y-%m-%d").date()
            d2 = datetime.strptime(hasta, "%Y-%m-%d").date()
            if d2 < d1:
                d1, d2 = d2, d1
            return d1, d2, f"Del {fecha_larga(d1)} al {fecha_larga(d2)}"
        except (ValueError, TypeError):
            pass
    try:
        a, m = (int(x) for x in mes.split("-"))
        date(a, m, 1)
    except (ValueError, TypeError, AttributeError):
        a, m = date.today().year, date.today().month
    d1, d2 = date(a, m, 1), date(a, m, calendar.monthrange(a, m)[1])
    return d1, d2, f"{MESES[m - 1].capitalize()} {a}"


def fecha_larga(d):
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(d):
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def nombre_archivo(*partes):
    import re
    t = "_".join(str(p) for p in partes if p)
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", t)[:90]


def _estado_texto(d):
    partes = []
    if d["estado"] == "falta":
        partes.append("Falta")
    elif d["estado"] == "descanso":
        partes.append("Descanso")
    elif d["estado"] == "incompleto":
        partes.append("Le faltó checar")
    elif d["estado"] == "en turno":
        partes.append("En turno")
    elif d["estado"] == "pendiente":
        partes.append("Aún no llega")
    elif d["estado"] == "festivo":
        partes.append(f"Festivo: {d['festivo']}")
    if d.get("festivo") and d["checadas"]:
        partes.append(f"Trabajó en festivo ({d['festivo']})")
    if d.get("justificacion") and d["plan"]:
        j = d["justificacion"]
        partes.append(j["texto"] + (f" — {j['nota']}" if j.get("nota") else ""))
    if d["retardo"]:
        partes.append(f"Retardo {int(d['retardo'])} min")
    if d["salio_antes"]:
        partes.append("Salió antes")
    if d["faltante"] and d["estado"] != "falta":
        partes.append(f"Faltaron {asistencia.fmt_horas(d['faltante'])} h")
    if d["extra"]:
        partes.append(f"Extra {asistencia.fmt_horas(d['extra'])} h")
    if not partes and d["checadas"]:
        partes.append("Bien")
    return " · ".join(partes)


# ---------------------------------------------------------------- PDF base
class Doc(FPDF):
    def __init__(self, titulo, subtitulo="", horizontal=False):
        super().__init__(orientation="L" if horizontal else "P", unit="mm", format="Letter")
        self.titulo, self.subtitulo = titulo, subtitulo
        self.empresa = db.cfg("empresa")
        self.set_margins(14, 14, 14)
        self.set_auto_page_break(True, 16)
        reg, neg = os.path.join(FUENTES, "LiberationSans-Regular.ttf"), os.path.join(FUENTES, "LiberationSans-Bold.ttf")
        if os.path.exists(reg) and os.path.exists(neg):
            self.add_font("Sans", "", reg)
            self.add_font("Sans", "B", neg)
            self.fuente = "Sans"
        else:
            self.fuente = "Helvetica"
        self.set_title(titulo)
        self.set_author(self.empresa)
        self.set_creator("Checador")

    def f(self, tam=9, negrita=False, color=TINTA):
        self.set_font(self.fuente, "B" if negrita else "", tam)
        self.set_text_color(*color)

    def header(self):
        self.f(8, True, GRIS)
        self.cell(0, 4, self.empresa.upper(), new_x="LMARGIN", new_y="NEXT")
        self.f(15, True, TINTA)
        self.cell(0, 8, self.titulo, new_x="LMARGIN", new_y="NEXT")
        if self.subtitulo:
            self.f(9.5, False, GRIS)
            self.cell(0, 5, self.subtitulo, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*AZUL)
        self.set_line_width(0.6)
        y = self.get_y() + 3
        self.line(self.l_margin, y, self.l_margin + 18, y)
        self.set_line_width(0.2)
        self.set_y(y + 6)

    def footer(self):
        self.set_y(-11)
        self.f(7.5, False, GRIS)
        self.cell(0, 4, f"Generado el {fecha_corta(date.today())} a las {datetime.now():%H:%M}", align="L")
        self.set_x(self.l_margin)
        self.cell(0, 4, f"Página {self.page_no()} de {{nb}}", align="R")

    def ajustar(self, texto, ancho):
        texto = str(texto if texto is not None else "")
        if self.get_string_width(texto) <= ancho - 2:
            return texto
        while texto and self.get_string_width(texto + "…") > ancho - 2:
            texto = texto[:-1]
        return texto + "…"

    def seccion(self, texto):
        if self.get_y() > self.page_break_trigger - 30:
            self.add_page()
        self.ln(3)
        self.f(11, True, TINTA)
        self.cell(0, 7, texto, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def cifras(self, items):
        """Fila de recuadros: [(valor, etiqueta, color)]."""
        ancho = (self.w - self.l_margin - self.r_margin - 4 * (len(items) - 1)) / len(items)
        y = self.get_y()
        for i, (valor, etiqueta, color) in enumerate(items):
            x = self.l_margin + i * (ancho + 4)
            self.set_fill_color(*AZUL_CLARO)
            self.rect(x, y, ancho, 17, style="F", round_corners=True, corner_radius=2)
            self.set_xy(x + 4, y + 2.5)
            self.f(14, True, color)
            self.cell(ancho - 8, 7, str(valor))
            self.set_xy(x + 4, y + 10)
            self.f(7.5, False, GRIS)
            self.cell(ancho - 8, 4, etiqueta)
        self.set_y(y + 22)

    def tabla(self, cols, filas, estilos=None, alto=6.6):
        """cols: [(titulo, ancho_mm, 'L'|'C'|'R')]; si la suma no da el ancho de la página, la última se estira."""
        util = self.w - self.l_margin - self.r_margin
        total = sum(c[1] for c in cols)
        cols = [list(c) for c in cols]
        cols[-1][1] += util - total

        def encabezado():
            self.set_fill_color(*AZUL_CLARO)
            self.f(7.5, True, AZUL)
            for t, w, a in cols:
                self.cell(w, 7, t.upper(), align=a, fill=True)
            self.ln(7)

        encabezado()
        self.set_draw_color(*LINEA)
        for i, fila in enumerate(filas):
            if self.get_y() + alto > self.page_break_trigger:
                self.add_page()
                encabezado()
            est = (estilos[i] if estilos else None) or {}
            self.f(8.5, est.get("negrita", False), est.get("color", TINTA))
            colores = est.get("colores", {})
            for j, ((t, w, a), v) in enumerate(zip(cols, fila)):
                if j in colores:
                    self.set_text_color(*colores[j])
                self.cell(w, alto, self.ajustar(v, w), align=a)
                if j in colores:
                    self.set_text_color(*est.get("color", TINTA))
            self.ln(alto)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())

    def salida(self):
        return bytes(self.output())


def _ruta_foto(emp):
    if not emp.get("foto"):
        return None
    mini = os.path.join(db.FOTOS, "mini", os.path.splitext(emp["foto"])[0] + ".jpg")
    if os.path.exists(mini):
        return mini
    original = os.path.join(db.FOTOS, emp["foto"])
    return original if os.path.exists(original) else None


def _foto(doc, emp, x, y, w, h):
    ruta = _ruta_foto(emp)
    doc.set_fill_color(*AZUL_CLARO)
    doc.rect(x, y, w, h, style="F", round_corners=True, corner_radius=2)
    if ruta:
        try:
            doc.image(ruta, x=x, y=y, w=w, h=h, keep_aspect_ratio=True)
            return
        except Exception:
            pass
    doc.set_xy(x, y + h / 2 - 5)
    doc.f(h * 0.9, True, AZUL)
    doc.cell(w, 10, (emp["nombre"][:1] + (emp["apellidos"] or "")[:1]).upper(), align="C")


# ---------------------------------------------------------------- reportes
def _encabezado_empleado(doc, r, completo):
    e = r["emp"]
    y0 = doc.get_y()
    fw, fh = (38, 48) if completo else (22, 27)
    _foto(doc, e, doc.l_margin, y0, fw, fh)
    x = doc.l_margin + fw + 7
    doc.set_xy(x, y0)
    doc.f(15 if completo else 13, True)
    doc.cell(0, 7, f"{e['nombre']} {e['apellidos']}".strip(), new_x="LMARGIN", new_y="NEXT")
    doc.set_x(x)
    doc.f(9.5, False, GRIS)
    linea = " · ".join(p for p in [f"No. {e['numero']}", e.get("departamento") or "", e.get("puesto") or ""] if p)
    doc.cell(0, 5.5, linea, new_x="LMARGIN", new_y="NEXT")
    doc.set_x(x)
    h = r["horario"]
    doc.cell(0, 5.5, f"Horario: {h['nombre']} ({h['resumen']})" if h else "Sin horario", new_x="LMARGIN", new_y="NEXT")
    if completo:
        campos = [("Ingreso", fecha_corta(datetime.strptime(e["fecha_ingreso"][:10], "%Y-%m-%d")) if e.get("fecha_ingreso") else ""),
                  ("Teléfono", e.get("telefono")), ("CURP", e.get("curp")), ("RFC", e.get("rfc")),
                  ("NSS", e.get("nss")), ("Correo", e.get("email")),
                  ("Nacimiento", fecha_corta(datetime.strptime(e["fecha_nacimiento"][:10], "%Y-%m-%d")) if e.get("fecha_nacimiento") else ""),
                  ("Salario", e.get("salario")),
                  ("Emergencia", " ".join(p for p in [e.get("contacto_emergencia"), e.get("tel_emergencia")] if p)),
                  ("Estado", "Activo" if e.get("activo") else f"Baja {e.get('fecha_baja') or ''}")]
        ancho = (doc.w - doc.r_margin - x) / 2
        doc.ln(2)
        for i in range(0, len(campos), 2):
            yy = doc.get_y()
            for j, (et, val) in enumerate(campos[i:i + 2]):
                doc.set_xy(x + j * ancho, yy)
                doc.f(7.5, False, GRIS)
                doc.cell(22, 5.2, et)
                doc.f(8.8, False, TINTA)
                doc.cell(ancho - 22, 5.2, doc.ajustar(val or "—", ancho - 22))
            doc.set_y(yy + 5.2)
        if e.get("direccion"):
            doc.set_x(x)
            doc.f(7.5, False, GRIS)
            doc.cell(22, 5.2, "Dirección")
            doc.f(8.8)
            doc.cell(0, 5.2, doc.ajustar(e["direccion"], doc.w - doc.r_margin - x - 22))
    doc.set_y(max(doc.get_y(), y0 + fh) + 7)


def _cifras_empleado(doc, r):
    items = [(r["asistencias"], "días trabajados", TINTA),
             (r["faltas"], "faltas", ROJO if r["faltas"] else TINTA),
             (r["retardos"], f"retardos ({int(r['min_retardo'])} min)", AMBAR if r["retardos"] else TINTA),
             (asistencia.fmt_horas(r["minutos"]), "horas trabajadas", TINTA)]
    if r["justificados"]:
        items.insert(2, (r["justificados"], "días justificados", AZUL))
    if r["extra"]:
        items.append((asistencia.fmt_horas(r["extra"]), "horas extra", VERDE))
    else:
        items.append((asistencia.fmt_horas(r["faltante"]), "horas que faltaron", ROJO if r["faltante"] > 59 else TINTA))
    doc.cifras(items)


def _tabla_dias(doc, r):
    cols = [("Fecha", 24, "L"), ("Día", 13, "L"), ("Horario", 34, "L"), ("Checadas", 52, "L"),
            ("Horas", 16, "R"), ("Estado", 40, "L")]
    filas, estilos = [], []
    for d in r["detalle"]:
        if d["estado"] == "" and not d["checadas"]:
            continue
        filas.append([fecha_corta(d["fecha"]), d["dia"], d["plan_texto"], d["texto"],
                      asistencia.fmt_horas(d["minutos"]) if d["minutos"] else "", _estado_texto(d)])
        if d["estado"] == "falta":
            estilos.append({"color": ROJO})
        elif d["estado"] in ("descanso", "festivo"):
            estilos.append({"color": GRIS})
        elif d["estado"] == "justificado":
            estilos.append({"colores": {5: AZUL}})
        elif d["retardo"] or d["salio_antes"] or d["estado"] == "incompleto":
            estilos.append({"colores": {5: AMBAR}})
        else:
            estilos.append(None)
    if filas:
        doc.tabla(cols, filas, estilos)
    else:
        doc.f(9, False, GRIS)
        doc.cell(0, 6, "Sin registros en este periodo.", new_x="LMARGIN", new_y="NEXT")


def _resumen_mensual(doc, r):
    meses = OrderedDict()
    for d in r["detalle"]:
        meses.setdefault((d["fecha"].year, d["fecha"].month), []).append(d)
    filas = []
    for (a, m), ds in meses.items():
        x = asistencia.resumir(r["emp"], r["horario"], ds)
        filas.append([f"{MESES[m - 1].capitalize()} {a}", x["asistencias"], x["faltas"], x["retardos"],
                      asistencia.fmt_horas(x["minutos"]), asistencia.fmt_horas(x["extra"]),
                      asistencia.fmt_horas(x["faltante"])])
    doc.tabla([("Mes", 40, "L"), ("Días", 18, "C"), ("Faltas", 18, "C"), ("Retardos", 20, "C"),
               ("Horas", 25, "R"), ("Extra", 22, "R"), ("Faltaron", 22, "R")], filas)


def pdf_empleados(numeros, desde, hasta, etiqueta, completo=False):
    titulo = "Historial del empleado" if completo else "Asistencia del empleado"
    doc = Doc(titulo, etiqueta)
    with db.db() as con:
        docs_por_emp = {}
        if completo:
            for d in con.execute("""SELECT d.*, e.numero FROM documentos d JOIN empleados e ON e.id=d.empleado_id
                                    ORDER BY d.tipo='contrato' DESC, d.subido DESC"""):
                docs_por_emp.setdefault(d["numero"], []).append(dict(d))
    resultados = []
    for n in numeros:
        _, res = asistencia.reporte(desde, hasta, numero=n, solo_activos=False)
        resultados += res
    if not resultados:
        doc.add_page()
        doc.f(10, False, GRIS)
        doc.cell(0, 8, "No hay empleados para este reporte.")
        return doc.salida()
    for r in resultados:
        doc.add_page()
        _encabezado_empleado(doc, r, completo)
        _cifras_empleado(doc, r)
        if completo and docs_por_emp.get(r["emp"]["numero"]):
            doc.seccion("Documentos en expediente")
            filas = []
            for d in docs_por_emp[r["emp"]["numero"]]:
                vig = ""
                if d["tipo"] == "contrato":
                    vig = f"Vence {fecha_corta(datetime.strptime(d['vence'], '%Y-%m-%d'))}" if d["vence"] else "Indefinido"
                filas.append([db.TIPOS_DOC.get(d["tipo"], d["tipo"]), d["nombre"], vig,
                              fecha_corta(datetime.strptime(d["subido"][:10], "%Y-%m-%d"))])
            doc.tabla([("Documento", 45, "L"), ("Archivo", 75, "L"), ("Vigencia", 34, "L"), ("Subido", 25, "L")], filas)
        if completo and (hasta - desde).days > 31:
            doc.seccion("Resumen por mes")
            _resumen_mensual(doc, r)
        doc.seccion("Detalle por día")
        _tabla_dias(doc, r)
    return doc.salida()


def pdf_general(desde, hasta, etiqueta, dep=None, dep_nombre=""):
    _, res = asistencia.reporte(desde, hasta, dep)
    return pdf_checadas(res, desde, hasta, "Reporte General de Asistencia", dep_nombre, resumen=True)


def pdf_incidencias(desde, hasta, etiqueta, dep=None, dep_nombre=""):
    _, res = asistencia.reporte(desde, hasta, dep)
    doc = Doc("Faltas y retardos", etiqueta + (f" · {dep_nombre}" if dep_nombre else ""))
    doc.add_page()
    con_inc = [r for r in res if r["faltas"] or r["retardos"] or r["incompletos"]]
    doc.cifras([(sum(r["faltas"] for r in res), "faltas", ROJO), (sum(r["retardos"] for r in res), "retardos", AMBAR),
                (sum(r["incompletos"] for r in res), "días sin checar salida", AMBAR),
                (len(con_inc), f"de {len(res)} empleados con incidencias", TINTA)])
    if not con_inc:
        doc.f(10, False, GRIS)
        doc.cell(0, 8, "Sin faltas ni retardos en este periodo.")
        return doc.salida()
    doc.seccion("Resumen")
    doc.tabla([("No.", 16, "L"), ("Nombre", 80, "L"), ("Faltas", 22, "C"), ("Retardos", 22, "C"),
               ("Min. tarde", 22, "C"), ("Sin salida", 22, "C")],
              [[r["emp"]["numero"], f"{r['emp']['nombre']} {r['emp']['apellidos']}", r["faltas"] or "",
                r["retardos"] or "", int(r["min_retardo"]) or "", r["incompletos"] or ""] for r in con_inc],
              [{"colores": {2: ROJO, 3: AMBAR, 4: AMBAR, 5: AMBAR}}] * len(con_inc))
    doc.seccion("Detalle")
    filas, estilos = [], []
    for r in con_inc:
        for d in r["detalle"]:
            if d["estado"] in ("falta", "incompleto") or d["retardo"] or d["salio_antes"]:
                filas.append([f"{r['emp']['nombre']} {r['emp']['apellidos']}", fecha_corta(d["fecha"]), d["dia"],
                              d["texto"] or "—", _estado_texto(d)])
                estilos.append({"colores": {4: ROJO if d["estado"] == "falta" else AMBAR}})
    doc.tabla([("Nombre", 66, "L"), ("Fecha", 24, "L"), ("Día", 13, "L"), ("Checadas", 44, "L"), ("Incidencia", 40, "L")],
              filas, estilos)
    return doc.salida()


def _filas_checadas(r):
    """Por día: fecha, 8 checadas (4 entradas/salidas), horas, retardo, extra y lo que faltó."""
    filas = []
    for d in r["detalle"]:
        if not d["checadas"] and d["estado"] in ("", "descanso", "pendiente", "festivo", "justificado"):
            continue
        c = [x.strftime("%H:%M") for x in d["checadas"]]
        if len(c) > 8:  # más de 4 pares: se conserva la última como salida
            c = c[:7] + c[-1:]
        falta = d["faltante"]
        if d["estado"] == "incompleto":
            falta = max(d["requerido"] - d["minutos"], 0)
        filas.append((d["fecha"], c + [""] * (8 - len(c)), d["minutos"], d["retardo"], d["extra"], falta))
    return filas


class DocReloj(Doc):
    """Formato del reporte de ZKTime: encabezado centrado y tablas con cuadrícula."""

    def header(self):
        self.f(17, True)
        self.cell(0, 9, self.empresa, align="C", new_x="LMARGIN", new_y="NEXT")
        self.f(11.5, True)
        self.cell(0, 7, self.titulo, align="C", new_x="LMARGIN", new_y="NEXT")
        self.f(9, True)
        self.cell(0, 6, self.subtitulo, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)


def pdf_checadas(res, desde, hasta, titulo="Reporte de Entradas y Salidas", dep_nombre="", resumen=False):
    doc = DocReloj(titulo, f"Desde {desde:%d.%m.%Y} Hasta {hasta:%d.%m.%Y}" + (f" · {dep_nombre}" if dep_nombre else ""))
    doc.add_page()
    util = doc.w - doc.l_margin - doc.r_margin
    cols = [("Fecha", 19)] + [("Entrada" if i % 2 == 0 else "Salida", 13.4) for i in range(8)] + \
           [("Total Horas", 15), ("Retardo", 14), ("T.E.", 13)]
    cols.append(("Falta", util - sum(w for _, w in cols)))
    alto, alto_enc, alto_firma = 5.2, 9, 12
    hm = asistencia.fmt_horas
    inicio = doc.get_y()  # donde empieza el contenido debajo del encabezado de la hoja

    def encabezado():
        doc.f(7.8, True)
        y = doc.get_y()
        for t, w in cols:
            x = doc.get_x()
            doc.rect(x, y, w, alto_enc)
            doc.multi_cell(w, alto_enc if " " not in t else alto_enc / 2, t, align="C", new_x="RIGHT", new_y="TOP")
            doc.set_xy(x + w, y)
        doc.set_xy(doc.l_margin, y + alto_enc)

    def firma(nombre):
        """Línea para la firma del empleado, a la derecha, debajo de su tabla."""
        ancho = 75
        x = doc.w - doc.r_margin - ancho
        y = doc.get_y() + 8
        doc.f(8, True)
        doc.set_xy(doc.l_margin, y - 4)
        doc.cell(x - doc.l_margin - 3, 4, "Firma del empleado:", align="R")
        doc.set_draw_color(0, 0, 0)
        doc.line(x, y, x + ancho, y)
        doc.set_xy(x, y + 0.5)
        doc.f(7.5, False, GRIS)
        doc.cell(ancho, 3.5, doc.ajustar(nombre, ancho), align="C")
        doc.set_xy(doc.l_margin, y + 4)

    def celda(w, texto, color=TINTA, align="C", negrita=False):
        doc.f(8, negrita, color)
        doc.cell(w, alto, texto, border=1, align=align)

    for r in res:
        e = r["emp"]
        filas = _filas_checadas(r)
        nombre = f"{e['nombre']} {e['apellidos']}".strip()
        # el bloque completo (datos, tabla, total y firma) no se parte si cabe en una hoja
        bloque = 9 + alto_enc + alto * (len(filas) + 1) + alto_firma
        if doc.get_y() > inicio + 1 and doc.get_y() + bloque > doc.page_break_trigger:
            doc.add_page()
        # datos del empleado
        y = doc.get_y()
        doc.set_draw_color(0, 0, 0)
        doc.rect(doc.l_margin, y, util, 9)
        partes = [("ID de\nUsuario", 15, e["numero"], 17), ("Nombre\nCompleto", 18, nombre, 68),
                  ("Departamento", 23, e.get("departamento") or "", util - 141)]
        x = doc.l_margin
        for et, we, val, wv in partes:
            doc.set_xy(x + 1, y + 0.5)
            doc.f(8, True)
            doc.multi_cell(we, 4, et, align="L", new_x="RIGHT", new_y="TOP")
            doc.set_xy(x + 1 + we, y + 0.5)
            doc.f(8)
            doc.multi_cell(wv - 1, 4, doc.ajustar(val, (wv - 1) * 2), align="L",
                           max_line_height=4, new_x="RIGHT", new_y="TOP")
            x += we + wv
        doc.set_xy(doc.l_margin, y + 9)
        encabezado()
        for fecha, c, minutos, retardo, extra, falta in filas:
            if doc.get_y() + alto > doc.page_break_trigger:
                doc.add_page()
                encabezado()
            celda(cols[0][1], f"{fecha:%d.%m.%Y}", align="L")
            for i in range(8):
                celda(cols[1 + i][1], c[i])
            celda(cols[9][1], hm(minutos))
            celda(cols[10][1], hm(retardo), AMBAR if retardo else TINTA)
            celda(cols[11][1], hm(extra))
            celda(cols[12][1], hm(falta), ROJO if falta >= 1 else TINTA)
            doc.ln(alto)
        if doc.get_y() + alto + alto_firma > doc.page_break_trigger:  # total y firma juntos
            doc.add_page()
            encabezado()
        celda(sum(w for _, w in cols[:9]), "Total", align="R")
        celda(cols[9][1], hm(sum(f[2] for f in filas)), negrita=True)
        celda(cols[10][1], hm(sum(f[3] for f in filas)), negrita=True)
        celda(cols[11][1], hm(sum(f[4] for f in filas)), negrita=True)
        celda(cols[12][1], hm(sum(f[5] for f in filas)), negrita=True)
        doc.ln(alto)
        firma(nombre)
        doc.ln(5)
    if not res:
        doc.f(10, False, GRIS)
        doc.cell(0, 8, "No hay empleados para este reporte.")
    elif resumen:
        _resumen_rejilla(doc, res, util, alto)
    return doc.salida()


def _resumen_rejilla(doc, res, util, alto):
    """Al final del reporte general: una fila por empleado con sus totales."""
    hm = asistencia.fmt_horas
    cols = [("ID", 14, "C"), ("Nombre", 46, "L"), ("Departamento", 24, "L"), ("Días", 11, "C"), ("Faltas", 13, "C"),
            ("Retardos", 16, "C"), ("Tiempo retardo", 0, "C"), ("Total Horas", 17, "C"), ("T.E.", 13, "C"), ("Falta", 15, "C")]
    cols[6] = (cols[6][0], util - sum(c[1] for c in cols), "C")

    def encabezado():
        doc.f(7.8, True)
        y = doc.get_y()
        for t, w, _ in cols:
            x = doc.get_x()
            doc.rect(x, y, w, 10)
            doc.multi_cell(w, 10 if " " not in t else 5, t, align="C", new_x="RIGHT", new_y="TOP")
            doc.set_xy(x + w, y)
        doc.set_xy(doc.l_margin, y + 10)

    doc.add_page()
    doc.f(11, True)
    doc.cell(0, 8, "Resumen", align="C", new_x="LMARGIN", new_y="NEXT")
    encabezado()
    tot = {k: 0 for k in ("asistencias", "faltas", "retardos", "min_retardo", "minutos", "extra", "faltante")}
    for r in res:
        if doc.get_y() + alto > doc.page_break_trigger:
            doc.add_page()
            encabezado()
        filas = _filas_checadas(r)
        falta = sum(f[5] for f in filas)
        e = r["emp"]
        valores = [e["numero"], f"{e['nombre']} {e['apellidos']}".strip(), e.get("departamento") or "",
                   r["asistencias"], r["faltas"], r["retardos"], hm(r["min_retardo"]), hm(r["minutos"]),
                   hm(r["extra"]), hm(falta)]
        colores = {4: ROJO if r["faltas"] else TINTA, 5: AMBAR if r["retardos"] else TINTA,
                   6: AMBAR if r["retardos"] else TINTA, 9: ROJO if falta >= 1 else TINTA}
        for k, ((_, w, a), v) in enumerate(zip(cols, valores)):
            doc.f(8, False, colores.get(k, TINTA))
            doc.cell(w, alto, doc.ajustar(v, w), border=1, align=a)
        doc.ln(alto)
        for k in tot:
            tot[k] += falta if k == "faltante" else r[k]
    if doc.get_y() + alto > doc.page_break_trigger:
        doc.add_page()
    doc.f(8, True)
    doc.cell(sum(c[1] for c in cols[:3]), alto, "Total", border=1, align="R")
    for (_, w, a), v in zip(cols[3:], [tot["asistencias"], tot["faltas"], tot["retardos"], hm(tot["min_retardo"]),
                                       hm(tot["minutos"]), hm(tot["extra"]), hm(tot["faltante"])]):
        doc.cell(w, alto, str(v), border=1, align=a)
    doc.ln(alto)


def pdf_directorio(dep=None, dep_nombre=""):
    with db.db() as con:
        emps = asistencia.empleados_con_horario(con, dep)
    doc = Doc("Directorio de empleados", f"{len(emps)} empleados activos" + (f" · {dep_nombre}" if dep_nombre else ""))
    doc.add_page()
    util = doc.w - doc.l_margin - doc.r_margin
    cw, ch, gap = (util - 8) / 3, 34, 4
    for i, e in enumerate(emps):
        col = i % 3
        if col == 0:
            if i:
                doc.set_y(y + ch + gap)
            if doc.get_y() + ch > doc.page_break_trigger:
                doc.add_page()
            y = doc.get_y()
        x = doc.l_margin + col * (cw + gap)
        doc.set_draw_color(*LINEA)
        doc.rect(x, y, cw, ch, style="D", round_corners=True, corner_radius=2)
        _foto(doc, e, x + 3, y + 3, 22, ch - 6)
        tx, tw = x + 28, cw - 31
        doc.set_xy(tx, y + 4)
        doc.f(8.8, True)
        doc.multi_cell(tw, 4.2, f"{e['nombre']} {e['apellidos']}".strip(), max_line_height=4.2, align="L",
                       new_x="LEFT", new_y="NEXT")
        for t in [f"No. {e['numero']}", e.get("departamento") or "", e.get("puesto") or "", e.get("telefono") or ""]:
            if t:
                doc.set_x(tx)
                doc.f(7.8, False, GRIS)
                doc.cell(tw, 4.2, doc.ajustar(t, tw), new_x="LEFT", new_y="NEXT")
    return doc.salida()


# ---------------------------------------------------------------- Excel
def _libro():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    estilo = {"enc_font": Font(bold=True, color="FFFFFF"), "enc_fill": PatternFill("solid", fgColor="2563EB"),
              "centro": Alignment(horizontal="center", vertical="center", wrap_text=True),
              "titulo": Font(bold=True, size=13)}
    return wb, estilo


def _hoja(ws, est, titulo, encabezados, filas, anchos):
    from openpyxl.utils import get_column_letter
    ws.append([titulo])
    ws["A1"].font = est["titulo"]
    ws.append([])
    ws.append(encabezados)
    for c in ws[3]:
        c.font, c.fill, c.alignment = est["enc_font"], est["enc_fill"], est["centro"]
    for f in filas:
        ws.append(f)
    ws.freeze_panes = "C4"
    for i, a in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(i)].width = a
    for fila in ws.iter_rows(min_row=4):
        for c in fila:
            if isinstance(c.value, date):
                c.number_format = "DD/MM/YYYY"


def _num(n):
    return int(n) if str(n).isdigit() else n


def _horas(m):
    return round((m or 0) / 60, 2)


def excel(res, dias, titulo_periodo, incluir_cuadro=True):
    wb, est = _libro()
    ws = wb.active
    ws.title = "Resumen"
    _hoja(ws, est, f"{db.cfg('empresa')} — {titulo_periodo}",
          ["No.", "Nombre", "Departamento", "Días trabajados", "Faltas", "Días justificados", "Retardos",
           "Min. de retardo", "Días sin checar salida", "Horas trabajadas", "Horas extra", "Horas que faltaron"],
          [[_num(r["emp"]["numero"]), f"{r['emp']['nombre']} {r['emp']['apellidos']}", r["emp"]["departamento"] or "",
            r["asistencias"], r["faltas"], r["justificados"], r["retardos"], round(r["min_retardo"]), r["incompletos"],
            _horas(r["minutos"]), _horas(r["extra"]), _horas(r["faltante"])] for r in res],
          [8, 34, 18, 12, 9, 12, 10, 12, 12, 12, 11, 12])
    ws2 = wb.create_sheet("Detalle por día")
    _hoja(ws2, est, f"Detalle — {titulo_periodo}",
          ["No.", "Nombre", "Fecha", "Día", "Horario", "Entrada", "Salida", "Todas las checadas", "Horas",
           "Retardo (min)", "Extra (h)", "Faltaron (h)", "Estado"],
          [[_num(r["emp"]["numero"]), f"{r['emp']['nombre']} {r['emp']['apellidos']}", d["fecha"], d["dia"],
            d["plan_texto"], d["checadas"][0].strftime("%H:%M") if d["checadas"] else "",
            d["checadas"][-1].strftime("%H:%M") if len(d["checadas"]) > 1 else "", d["texto"],
            _horas(d["minutos"]) if d["minutos"] else "", round(d["retardo"]) or "",
            _horas(d["extra"]) if d["extra"] else "", _horas(d["faltante"]) if d["faltante"] >= 1 else "",
            _estado_texto(d)]
           for r in res for d in r["detalle"] if d["estado"] or d["checadas"]],
          [8, 32, 12, 7, 22, 9, 9, 28, 8, 11, 9, 11, 30])
    _hoja_checadas(wb.create_sheet("Entradas y salidas"), est, res, titulo_periodo)
    if incluir_cuadro and len(dias) <= 31:
        ws3 = wb.create_sheet("Cuadro")
        enc = ["No.", "Nombre"] + [f"{asistencia.DIAS_CORTOS[d.weekday()]} {d.day}/{d.month}" for d in dias] + ["Horas"]
        filas = []
        for r in res:
            fila = [_num(r["emp"]["numero"]), f"{r['emp']['nombre']} {r['emp']['apellidos']}"]
            for d in r["detalle"]:
                if d["checadas"]:
                    fila.append(d["checadas"][0].strftime("%H:%M") + "–" +
                                (d["checadas"][-1].strftime("%H:%M") if len(d["checadas"]) > 1 else "?"))
                else:
                    fila.append({"falta": "FALTA", "descanso": "·", "festivo": "FESTIVO",
                                 "justificado": (d["justificacion"] or {}).get("abrev", "JUSTIF.").upper()
                                 }.get(d["estado"], ""))
            fila.append(_horas(r["minutos"]))
            filas.append(fila)
        _hoja(ws3, est, f"Entradas y salidas — {titulo_periodo}", enc, filas, [8, 32] + [12] * len(dias) + [9])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _hoja_checadas(ws, est, res, titulo_periodo):
    filas = []
    for r in res:
        for fecha, c, minutos, retardo, extra, falta in _filas_checadas(r):
            filas.append([_num(r["emp"]["numero"]), f"{r['emp']['nombre']} {r['emp']['apellidos']}",
                          r["emp"]["departamento"] or "", fecha] + c +
                         [_horas(minutos), round(retardo) or "", _horas(extra) if extra else "",
                          _horas(falta) if falta >= 1 else ""])
    _hoja(ws, est, f"{db.cfg('empresa')} — Entradas y salidas — {titulo_periodo}",
          ["No.", "Nombre", "Departamento", "Fecha"] + ["Entrada", "Salida"] * 4 +
          ["Total horas", "Retardo (min)", "T.E. (h)", "Falta (h)"], filas,
          [8, 32, 16, 12] + [9] * 8 + [11, 12, 9, 9])


def excel_checadas(res, titulo_periodo):
    wb, est = _libro()
    ws = wb.active
    ws.title = "Entradas y salidas"
    _hoja_checadas(ws, est, res, titulo_periodo)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
