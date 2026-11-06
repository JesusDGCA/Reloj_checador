"""Checador Simple — aplicación para el reloj checador Steren CLK-960 (y compatibles ZKTeco).

Ejecutar:  python app.py      (abre el navegador en http://localhost:8080)
"""
import io
import json
import os
import sys
import threading
import time
import webbrowser
import zipfile
from datetime import date, datetime, timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from flask.sessions import SecureCookieSessionInterface

import asistencia
import db
import reloj
import reportes

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB por archivo
class _SesionConClave(SecureCookieSessionInterface):
    """La clave secreta (para firmar la sesión) se genera al azar y se guarda en la base de datos.
    Se carga la primera vez que Flask la necesita, porque la base se prepara después de importar este módulo."""
    def get_signing_serializer(self, app_):
        if not app_.secret_key:
            app_.secret_key = db.clave_secreta()
        return super().get_signing_serializer(app_)


app.session_interface = _SesionConClave()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tif", ".tiff"}
TIPOS_DOC = db.TIPOS_DOC
MINI = os.path.join(db.FOTOS, "mini")
MIN_CONTRASENA = 6


# ---------------------------------------------------------------- inicio de sesión
PUBLICAS = {"login", "configurar", "static", "api_ping", "favicon"}


def _es_local():
    return request.remote_addr in ("127.0.0.1", "::1")


def _destino_seguro(url):
    """Solo permite volver a una página de este mismo programa (evita redirecciones a otros sitios)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return url_for("inicio")


@app.before_request
def _exigir_sesion():
    g.usuario = None
    uid = session.get("usuario_id")
    if uid:
        with db.db() as con:
            u = con.execute("SELECT id, usuario, nombre FROM usuarios WHERE id=? AND activo=1", (uid,)).fetchone()
        if u:
            g.usuario = dict(u)
        else:  # lo dieron de baja o lo borraron: se cierra su sesión
            session.clear()
    if g.usuario or request.endpoint in PUBLICAS:
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="sesion"), 401
    if not db.hay_usuarios():
        return redirect(url_for("configurar"))
    return redirect(url_for("login", siguiente=request.full_path if request.method == "GET" else None))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not db.hay_usuarios():
        return redirect(url_for("configurar"))
    siguiente = request.values.get("siguiente", "")
    if g.usuario:
        return redirect(_destino_seguro(siguiente))
    usuario = request.form.get("usuario", "").strip()
    if request.method == "POST":
        u = db.verificar_usuario(usuario, request.form.get("contrasena", ""))
        if u:
            session.clear()
            session["usuario_id"] = u["id"]
            db.log(f"Inicio de sesión: {u['usuario']} ({request.remote_addr})")
            return redirect(_destino_seguro(siguiente))
        time.sleep(1)  # frena a quien intente adivinar contraseñas
        db.log(f"Intento fallido de inicio de sesión: {usuario} ({request.remote_addr})", "error")
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html", usuario=usuario, siguiente=siguiente)


@app.route("/configurar", methods=["GET", "POST"])
def configurar():
    """Primera vez: crear el usuario administrador. Solo se puede desde esta misma computadora."""
    if db.hay_usuarios():
        return redirect(url_for("login"))
    if not _es_local():
        return render_template("login.html", sin_usuarios=True), 403
    datos = {k: request.form.get(k, "").strip() for k in ("usuario", "nombre")}
    if request.method == "POST":
        error = _validar_usuario_nuevo(datos["usuario"], request.form.get("contrasena", ""),
                                       request.form.get("contrasena2", ""))
        if error:
            flash(error, "error")
        else:
            db.crear_usuario(datos["usuario"], request.form["contrasena"], datos["nombre"])
            db.log(f"Usuario administrador creado: {datos['usuario']}")
            flash("Listo. Ya puedes entrar con tu usuario y contraseña.", "ok")
            return redirect(url_for("login"))
    return render_template("login.html", configurar=True, **datos)


@app.route("/logout", methods=["POST"])
def logout():
    db.log("Cerró sesión")
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("login"))


def _validar_usuario_nuevo(usuario, contrasena, contrasena2):
    if not usuario:
        return "Escribe un nombre de usuario."
    if len(contrasena) < MIN_CONTRASENA:
        return f"La contraseña debe tener al menos {MIN_CONTRASENA} caracteres."
    if contrasena != contrasena2:
        return "Las contraseñas no coinciden."
    with db.db() as con:
        if con.execute("SELECT 1 FROM usuarios WHERE usuario=?", (usuario,)).fetchone():
            return "Ya existe un usuario con ese nombre."
    return None


# ---------------------------------------------------------------- utilidades
@app.context_processor
def globales():
    return {"usuario_actual": g.get("usuario"),
            "empresa": db.cfg("empresa"), "hoy": date.today(), "TIPOS_DOC": TIPOS_DOC,
            "TIPOS_JUSTIFICACION": db.TIPOS_JUSTIFICACION,
            "fmt_horas": asistencia.fmt_horas, "DIAS": asistencia.DIAS,
            "estado_reloj": _estado_reloj(), "portatil": os.environ.get("CHECADOR_PORTATIL") == "1"}


def _estado_reloj():
    ok, err = db.cfg("ultima_sync_ok"), db.cfg("ultimo_error")
    return {"ok": not err and bool(ok), "ultima": ok, "error": err,
            "simulado": db.cfg("reloj_ip").lower() == "simulado"}


@app.template_filter("tam")
def tam(n):
    n = n or 0
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


@app.template_filter("fecha")
def fecha_filtro(v):
    if not v:
        return ""
    if isinstance(v, str):
        try:
            v = datetime.strptime(v[:10], "%Y-%m-%d").date()
        except ValueError:
            return v
    meses = "ene feb mar abr may jun jul ago sep oct nov dic".split()
    return f"{v.day} {meses[v.month - 1]} {v.year}"


def _fecha(arg, default):
    try:
        return datetime.strptime(request.args.get(arg, ""), "%Y-%m-%d").date()
    except ValueError:
        return default


def _miniatura(archivo):
    """Crea una versión chica de la foto para las listas (la original se conserva)."""
    try:
        from PIL import Image, ImageOps
        os.makedirs(MINI, exist_ok=True)
        with Image.open(os.path.join(db.FOTOS, archivo)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((360, 360))
            im.save(os.path.join(MINI, os.path.splitext(archivo)[0] + ".jpg"), "JPEG", quality=82)
    except Exception:
        pass


def _empleado(id_):
    with db.db() as con:
        e = con.execute("""SELECT e.*, d.nombre AS departamento FROM empleados e
                           LEFT JOIN departamentos d ON d.id = e.departamento_id WHERE e.id=?""", (id_,)).fetchone()
    if not e:
        abort(404)
    return dict(e)


def _accion_reloj(funcion, ok_msg):
    try:
        r = funcion()
        flash(ok_msg.format(r=r), "ok")
    except reloj.RelojError as e:
        flash(str(e), "error")
        db.log(str(e), "error")
    except Exception as e:
        flash(f"Error inesperado: {e}", "error")
        db.log(f"Error inesperado: {e}", "error")


def _volver(default="inicio"):
    return redirect(request.form.get("volver") or request.referrer or url_for(default))


# ---------------------------------------------------------------- inicio
@app.route("/")
def inicio():
    resumen = asistencia.hoy()
    hoy = date.today()
    with db.db() as con:
        por_vencer = con.execute("""SELECT d.*, e.nombre, e.apellidos, e.id AS emp_id FROM documentos d
              JOIN empleados e ON e.id = d.empleado_id
              WHERE d.tipo='contrato' AND d.vence != '' AND d.vence <= ? AND e.activo=1
              ORDER BY d.vence""", ((hoy + timedelta(days=30)).isoformat(),)).fetchall()
        sin_contrato = con.execute("""SELECT COUNT(*) FROM empleados e WHERE activo=1 AND NOT EXISTS
              (SELECT 1 FROM documentos d WHERE d.empleado_id=e.id AND d.tipo='contrato')""").fetchone()[0]
        sin_huella = con.execute("""SELECT COUNT(*) FROM empleados e WHERE activo=1 AND NOT EXISTS
              (SELECT 1 FROM huellas h WHERE h.numero=e.numero)""").fetchone()[0]
    with db.db() as con:
        vacio = not con.execute("SELECT 1 FROM empleados LIMIT 1").fetchone()
    if vacio:
        return render_template("bienvenida.html", cfg_ip=db.cfg("reloj_ip"))
    return render_template("inicio.html", r=resumen, por_vencer=por_vencer,
                           sin_contrato=sin_contrato, sin_huella=sin_huella)


@app.route("/api/ping")
def api_ping():
    return jsonify(app="checador")


@app.route("/apagar", methods=["POST"])
def apagar():
    """Solo en modo portátil: apaga el programa para poder sacar la USB sin dañar los datos."""
    if os.environ.get("CHECADOR_PORTATIL") != "1" or not _es_local():
        abort(404)
    db.log("Cerró Checador portátil")
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return render_template("login.html", apagado=True)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "checador.ico")


@app.route("/api/ultimas")
def api_ultimas():
    with db.db() as con:
        filas = con.execute("""SELECT c.numero, c.fecha_hora, c.origen, e.id, e.nombre, e.apellidos, e.foto,
                                      d.nombre AS departamento
            FROM checadas c LEFT JOIN empleados e ON e.numero = c.numero
            LEFT JOIN departamentos d ON d.id = e.departamento_id
            ORDER BY c.fecha_hora DESC LIMIT 20""").fetchall()
    hoy = date.today().isoformat()
    return jsonify(ultimas=[{
        "numero": f["numero"], "nombre": f"{f['nombre'] or 'Sin registrar'} {f['apellidos'] or ''}".strip(),
        "depto": f["departamento"] or "", "hora": f["fecha_hora"][11:16],
        "fecha": "" if f["fecha_hora"][:10] == hoy else fecha_filtro(f["fecha_hora"]),
        "foto": url_for("foto_mini", archivo=f["foto"]) if f["foto"] else "",
        "url": url_for("empleado", id_=f["id"]) if f["id"] else ""} for f in filas],
        estado=_estado_reloj())


@app.route("/sincronizar", methods=["POST"])
def sincronizar():
    _accion_reloj(reloj.sincronizar, "Listo: {r} checadas nuevas.")
    return _volver()


# ---------------------------------------------------------------- empleados
@app.route("/empleados")
def empleados():
    q = request.args.get("q", "").strip()
    dep = request.args.get("dep", "")
    ver = request.args.get("ver", "activos")
    sql = """SELECT e.*, d.nombre AS departamento,
               EXISTS(SELECT 1 FROM huellas h WHERE h.numero=e.numero) AS tiene_huella,
               (SELECT MAX(vence) FROM documentos x WHERE x.empleado_id=e.id AND x.tipo='contrato') AS contrato_vence,
               EXISTS(SELECT 1 FROM documentos x WHERE x.empleado_id=e.id AND x.tipo='contrato') AS tiene_contrato
             FROM empleados e LEFT JOIN departamentos d ON d.id=e.departamento_id WHERE 1=1"""
    args = []
    if ver == "activos":
        sql += " AND e.activo=1"
    elif ver == "bajas":
        sql += " AND e.activo=0"
    if dep:
        sql += " AND e.departamento_id=?"
        args.append(dep)
    if q:
        sql += " AND (e.nombre || ' ' || e.apellidos LIKE ? OR e.numero LIKE ? OR e.puesto LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY CAST(e.numero AS INTEGER), e.numero"
    with db.db() as con:
        lista = con.execute(sql, args).fetchall()
        deps = con.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
    return render_template("empleados.html", lista=lista, deps=deps, q=q, dep=dep, ver=ver)


CAMPOS = ["numero", "nombre", "apellidos", "departamento_id", "horario_id", "puesto", "telefono", "email",
          "curp", "rfc", "nss", "direccion", "fecha_nacimiento", "fecha_ingreso", "salario",
          "contacto_emergencia", "tel_emergencia", "notas"]


def _datos_form():
    d = {c: request.form.get(c, "").strip() for c in CAMPOS}
    d["nombre"] = d["nombre"].upper()
    d["apellidos"] = d["apellidos"].upper()
    d["curp"], d["rfc"] = d["curp"].upper(), d["rfc"].upper()
    for c in ("departamento_id", "horario_id"):
        d[c] = int(d[c]) if d[c] else None
    return d


@app.route("/empleados/nuevo", methods=["GET", "POST"])
def empleado_nuevo():
    with db.db() as con:
        deps = con.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
        hors = con.execute("SELECT * FROM horarios ORDER BY nombre").fetchall()
        siguiente = con.execute("SELECT COALESCE(MAX(CAST(numero AS INTEGER)), 0) + 1 FROM empleados").fetchone()[0]
    if request.method == "POST":
        d = _datos_form()
        if not d["numero"] or not d["nombre"]:
            flash("El número y el nombre son obligatorios.", "error")
            return render_template("empleado_nuevo.html", deps=deps, hors=hors, e=d, siguiente=siguiente)
        try:
            with db.db() as con:
                cur = con.execute(f"INSERT INTO empleados ({','.join(CAMPOS)}) VALUES ({','.join('?' * len(CAMPOS))})",
                                  [d[c] for c in CAMPOS])
                nuevo = cur.lastrowid
        except Exception:
            flash(f"Ya existe un empleado con el número {d['numero']}.", "error")
            return render_template("empleado_nuevo.html", deps=deps, hors=hors, e=d, siguiente=siguiente)
        db.log(f"Alta de empleado {d['numero']} {d['nombre']}")
        if request.form.get("enviar_reloj"):
            _accion_reloj(lambda: reloj.enviar_empleados([d]),
                          "Empleado enviado al reloj. Ahora registra su huella en el reloj: "
                          "Menú › Usuarios › Usuarios › elige su número › Editar › Agregar Huella.")
        flash("Empleado guardado.", "ok")
        return redirect(url_for("empleado", id_=nuevo))
    return render_template("empleado_nuevo.html", deps=deps, hors=hors, e={"numero": siguiente}, siguiente=siguiente)


@app.route("/empleados/<int:id_>", methods=["GET", "POST"])
def empleado(id_):
    e = _empleado(id_)
    if request.method == "POST":
        d = _datos_form()
        nombre_cambio = (d["nombre"], d["apellidos"], d["numero"]) != (e["nombre"], e["apellidos"], e["numero"])
        try:
            with db.db() as con:
                con.execute(f"UPDATE empleados SET {','.join(c + '=?' for c in CAMPOS)} WHERE id=?",
                            [d[c] for c in CAMPOS] + [id_])
                if d["numero"] != e["numero"]:
                    con.execute("UPDATE checadas SET numero=? WHERE numero=?", (d["numero"], e["numero"]))
                    con.execute("UPDATE huellas SET numero=? WHERE numero=?", (d["numero"], e["numero"]))
        except Exception:
            flash(f"El número {d['numero']} ya lo tiene otro empleado.", "error")
            return redirect(url_for("empleado", id_=id_))
        cambios = _diferencias(e, d)
        if cambios:
            db.log(f"Editó al empleado {e['numero']} {e['nombre']} {e['apellidos']}: {cambios}")
        flash("Cambios guardados.", "ok")
        if nombre_cambio and request.form.get("enviar_reloj"):
            _accion_reloj(lambda: reloj.enviar_empleados([d]), "Nombre actualizado en el reloj.")
        return redirect(url_for("empleado", id_=id_))

    hasta = _fecha("hasta", date.today())
    desde = _fecha("desde", hasta.replace(day=1))
    _, rep = asistencia.reporte(desde, hasta, numero=e["numero"], solo_activos=False)
    with db.db() as con:
        docs = con.execute("SELECT * FROM documentos WHERE empleado_id=? ORDER BY tipo='contrato' DESC, subido DESC",
                           (id_,)).fetchall()
        huellas = con.execute("SELECT dedo, actualizado FROM huellas WHERE numero=? ORDER BY dedo", (e["numero"],)).fetchall()
        deps = con.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
        hors = con.execute("SELECT * FROM horarios ORDER BY nombre").fetchall()
        justifs = con.execute("SELECT * FROM justificaciones WHERE empleado_id=? ORDER BY desde DESC",
                              (id_,)).fetchall()
    return render_template("empleado.html", e=e, docs=docs, huellas=huellas, deps=deps, hors=hors,
                           rep=rep[0] if rep else None, desde=desde, hasta=hasta, justifs=justifs)


ETIQUETAS_CAMPOS = {"numero": "número", "nombre": "nombre", "apellidos": "apellidos", "departamento_id": "departamento",
                    "horario_id": "horario", "puesto": "puesto", "telefono": "teléfono", "email": "correo",
                    "curp": "CURP", "rfc": "RFC", "nss": "NSS", "direccion": "dirección",
                    "fecha_nacimiento": "fecha de nacimiento", "fecha_ingreso": "fecha de ingreso",
                    "salario": "salario", "contacto_emergencia": "contacto de emergencia",
                    "tel_emergencia": "tel. de emergencia", "notas": "notas"}


def _diferencias(antes, despues):
    """Texto con lo que cambió: 'puesto: "CAJERO" → "GERENTE"; salario: "" → "9000"'."""
    def nombre_de(tabla, id_):
        if not id_:
            return "(ninguno)"
        with db.db() as con:
            fila = con.execute(f"SELECT nombre FROM {tabla} WHERE id=?", (id_,)).fetchone()
        return fila["nombre"] if fila else str(id_)

    partes = []
    for c in CAMPOS:
        a, b = antes.get(c), despues.get(c)
        if (a or "") == (b or ""):
            continue
        if c == "departamento_id":
            a, b = nombre_de("departamentos", a), nombre_de("departamentos", b)
        elif c == "horario_id":
            a, b = nombre_de("horarios", a), nombre_de("horarios", b)
        corto = lambda v: (str(v or "")[:60] + ("…" if len(str(v or "")) > 60 else ""))
        partes.append(f'{ETIQUETAS_CAMPOS.get(c, c)}: "{corto(a)}" → "{corto(b)}"')
    return "; ".join(partes)


# ---------------------------------------------------------------- justificar faltas
@app.route("/empleados/<int:id_>/justificar", methods=["POST"])
def justificar(id_):
    e = _empleado(id_)
    f = request.form
    tipo = f.get("tipo", "")
    try:
        d1 = datetime.strptime(f.get("desde", ""), "%Y-%m-%d").date()
        d2 = datetime.strptime(f.get("hasta") or f.get("desde", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Indica la fecha (o el rango de fechas).", "error")
        return redirect(url_for("empleado", id_=id_) + "#asistencia")
    if tipo not in db.TIPOS_JUSTIFICACION:
        flash("Elige el motivo.", "error")
        return redirect(url_for("empleado", id_=id_) + "#asistencia")
    if d2 < d1:
        d1, d2 = d2, d1
    if (d2 - d1).days > 366:
        flash("El periodo no puede ser mayor a un año.", "error")
        return redirect(url_for("empleado", id_=id_) + "#asistencia")
    nota = f.get("nota", "").strip()
    with db.db() as con:
        con.execute("INSERT INTO justificaciones (empleado_id, desde, hasta, tipo, nota, usuario) VALUES (?,?,?,?,?,?)",
                    (id_, d1.isoformat(), d2.isoformat(), tipo, nota, db.usuario_actual()))
    dias = (d2 - d1).days + 1
    periodo = f"el {d1:%d/%m/%Y}" if dias == 1 else f"del {d1:%d/%m/%Y} al {d2:%d/%m/%Y} ({dias} días)"
    db.log(f"Justificó {db.TIPOS_JUSTIFICACION[tipo].lower()} a {e['numero']} {e['nombre']} {e['apellidos']} "
           f"{periodo}" + (f" — {nota}" if nota else ""))
    flash(f"{db.TIPOS_JUSTIFICACION[tipo]} registrado {periodo}.", "ok")
    return redirect(url_for("empleado", id_=id_, desde=request.form.get("ver_desde") or None,
                            hasta=request.form.get("ver_hasta") or None) + "#asistencia")


@app.route("/justificaciones/<int:j_id>/borrar", methods=["POST"])
def justificacion_borrar(j_id):
    with db.db() as con:
        j = con.execute("""SELECT j.*, e.numero, e.nombre, e.apellidos FROM justificaciones j
                           JOIN empleados e ON e.id=j.empleado_id WHERE j.id=?""", (j_id,)).fetchone()
        if not j:
            abort(404)
        con.execute("DELETE FROM justificaciones WHERE id=?", (j_id,))
    db.log(f"Quitó la justificación ({db.TIPOS_JUSTIFICACION.get(j['tipo'], j['tipo'])} del {j['desde']} al "
           f"{j['hasta']}) de {j['numero']} {j['nombre']} {j['apellidos']}")
    flash("Justificación eliminada. Esos días vuelven a calcularse normalmente.", "ok")
    return redirect(url_for("empleado", id_=j["empleado_id"]) + "#asistencia")


@app.route("/empleados/<int:id_>/foto", methods=["POST"])
def empleado_foto(id_):
    e = _empleado(id_)
    f = request.files.get("foto")
    if not f or not f.filename:
        flash("Elige una foto.", "error")
        return redirect(url_for("empleado", id_=id_))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in EXT_FOTO:
        flash("Ese archivo no parece una foto (usa JPG, PNG, WEBP…).", "error")
        return redirect(url_for("empleado", id_=id_))
    nombre = f"{e['numero']}_{int(time.time())}{ext}"
    f.save(os.path.join(db.FOTOS, nombre))
    _miniatura(nombre)
    if e["foto"]:
        for p in (os.path.join(db.FOTOS, e["foto"]), os.path.join(MINI, os.path.splitext(e["foto"])[0] + ".jpg")):
            if os.path.exists(p):
                os.remove(p)
    with db.db() as con:
        con.execute("UPDATE empleados SET foto=? WHERE id=?", (nombre, id_))
    db.log(f"Cambió la foto de {e['numero']} {e['nombre']} {e['apellidos']}")
    flash("Foto actualizada.", "ok")
    return redirect(url_for("empleado", id_=id_))


@app.route("/fotos/<path:archivo>")
def foto(archivo):
    return send_from_directory(db.FOTOS, archivo)


@app.route("/fotos/mini/<path:archivo>")
def foto_mini(archivo):
    mini = os.path.splitext(archivo)[0] + ".jpg"
    if not os.path.exists(os.path.join(MINI, mini)) and os.path.exists(os.path.join(db.FOTOS, archivo)):
        _miniatura(archivo)
    if os.path.exists(os.path.join(MINI, mini)):
        return send_from_directory(MINI, mini, max_age=86400)
    return send_from_directory(db.FOTOS, archivo)


@app.route("/empleados/<int:id_>/documentos", methods=["POST"])
def documento_subir(id_):
    e = _empleado(id_)
    archivos = [f for f in request.files.getlist("archivo") if f and f.filename]
    if not archivos:
        flash("Elige un archivo.", "error")
        return redirect(url_for("empleado", id_=id_) + "#documentos")
    tipo = request.form.get("tipo", "otro")
    for i, f in enumerate(archivos):
        ext = os.path.splitext(f.filename)[1].lower()
        guardado = f"{e['numero']}_{tipo}_{int(time.time())}_{i}{ext}"
        ruta = os.path.join(db.DOCS, guardado)
        f.save(ruta)
        with db.db() as con:
            con.execute("""INSERT INTO documentos (empleado_id, tipo, nombre, archivo, tamano, inicio, vence, notas)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (id_, tipo, f.filename, guardado, os.path.getsize(ruta),
                         request.form.get("inicio", ""), request.form.get("vence", ""), request.form.get("notas", "")))
    db.log(f"Subió {TIPOS_DOC.get(tipo, 'documento').lower()} de {e['numero']} {e['nombre']} {e['apellidos']}: "
           + ", ".join(f.filename for f in archivos))
    flash(f"{TIPOS_DOC.get(tipo, 'Documento')} guardado.", "ok")
    return redirect(url_for("empleado", id_=id_) + "#documentos")


@app.route("/documentos/<int:doc_id>")
def documento(doc_id):
    with db.db() as con:
        d = con.execute("SELECT * FROM documentos WHERE id=?", (doc_id,)).fetchone()
    if not d:
        abort(404)
    return send_from_directory(db.DOCS, d["archivo"], download_name=d["nombre"],
                               as_attachment=request.args.get("descargar") == "1")


@app.route("/documentos/<int:doc_id>/borrar", methods=["POST"])
def documento_borrar(doc_id):
    with db.db() as con:
        d = con.execute("SELECT * FROM documentos WHERE id=?", (doc_id,)).fetchone()
        if d:
            con.execute("DELETE FROM documentos WHERE id=?", (doc_id,))
    if d:
        ruta = os.path.join(db.DOCS, d["archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
        emp = _empleado(d["empleado_id"])
        db.log(f"Eliminó {TIPOS_DOC.get(d['tipo'], 'documento').lower()} \"{d['nombre']}\" de "
               f"{emp['numero']} {emp['nombre']} {emp['apellidos']}")
        flash("Documento eliminado.", "ok")
        return redirect(url_for("empleado", id_=d["empleado_id"]) + "#documentos")
    return redirect(url_for("empleados"))


@app.route("/empleados/<int:id_>/reloj", methods=["POST"])
def empleado_reloj(id_):
    e = _empleado(id_)
    accion = request.form.get("accion")
    textos = {"enviar": "Envió al reloj a", "huellas": "Cargó al reloj las huellas de", "quitar": "Quitó del reloj a"}
    if accion in textos:
        db.log(f"{textos[accion]} {e['numero']} {e['nombre']} {e['apellidos']}")
    if accion == "enviar":
        _accion_reloj(lambda: reloj.enviar_empleados([e]), "Enviado al reloj.")
    elif accion == "huellas":
        _accion_reloj(lambda: reloj.restaurar_huellas([e]), "Se cargaron {r} huellas al reloj.")
    elif accion == "quitar":
        _accion_reloj(lambda: reloj.borrar_empleado(e["numero"]),
                      "Quitado del reloj (sus huellas siguen respaldadas aquí).")
    return redirect(url_for("empleado", id_=id_))


@app.route("/empleados/<int:id_>/estado", methods=["POST"])
def empleado_estado(id_):
    e = _empleado(id_)
    if e["activo"]:
        fecha = request.form.get("fecha_baja") or date.today().isoformat()
        with db.db() as con:
            con.execute("UPDATE empleados SET activo=0, fecha_baja=? WHERE id=?", (fecha, id_))
        db.log(f"Dio de baja al empleado {e['numero']} {e['nombre']} {e['apellidos']} con fecha {fecha}")
        if request.form.get("quitar_reloj"):
            _accion_reloj(lambda: reloj.borrar_empleado(e["numero"]), "También se quitó del reloj.")
        flash("Empleado dado de baja. Su expediente se conserva.", "ok")
    else:
        with db.db() as con:
            con.execute("UPDATE empleados SET activo=1, fecha_baja='' WHERE id=?", (id_,))
        db.log(f"Reactivó al empleado {e['numero']} {e['nombre']} {e['apellidos']}")
        flash("Empleado reactivado.", "ok")
    return redirect(url_for("empleado", id_=id_))


@app.route("/empleados/<int:id_>/checada", methods=["POST"])
def checada_manual(id_):
    e = _empleado(id_)
    f, h = request.form.get("fecha"), request.form.get("hora")
    if not f or not h:
        flash("Indica fecha y hora.", "error")
    else:
        with db.db() as con:
            con.execute("INSERT OR IGNORE INTO checadas (numero, fecha_hora, origen, nota) VALUES (?,?,'manual',?)",
                        (e["numero"], f"{f} {h}:00", request.form.get("nota", "")))
        db.log(f"Agregó checada a mano a {e['numero']} {e['nombre']} {e['apellidos']}: {f} {h}"
               + (f" — {request.form.get('nota')}" if request.form.get("nota") else ""))
        flash("Checada agregada.", "ok")
    return _volver()


@app.route("/checadas/borrar", methods=["POST"])
def checada_borrar():
    numero, fh = request.form.get("numero"), request.form.get("fecha_hora")
    with db.db() as con:
        n = con.execute("DELETE FROM checadas WHERE numero=? AND fecha_hora=? AND origen='manual'", (numero, fh)).rowcount
    if n:
        db.log(f"Eliminó la checada manual de {numero} del {fh}")
    flash("Checada manual eliminada.", "ok")
    return _volver()


# ---------------------------------------------------------------- asistencia
def _rango():
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    return _fecha("desde", lunes), _fecha("hasta", hoy)


@app.route("/asistencia")
def asistencia_vista():
    desde, hasta = _rango()
    if hasta < desde:
        desde, hasta = hasta, desde
    if (hasta - desde).days > 62:
        desde = hasta - timedelta(days=62)
        flash("Se muestran como máximo 2 meses.", "error")
    dep = request.args.get("dep", "")
    dias, res = asistencia.reporte(desde, hasta, int(dep) if dep else None)
    with db.db() as con:
        deps = con.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)
    mes_pasado_fin = inicio_mes - timedelta(days=1)
    rangos = [("Hoy", hoy, hoy), ("Esta semana", lunes, hoy),
              ("Semana pasada", lunes - timedelta(days=7), lunes - timedelta(days=1)),
              ("Este mes", inicio_mes, hoy), ("Mes pasado", mes_pasado_fin.replace(day=1), mes_pasado_fin)]
    return render_template("asistencia.html", dias=dias, res=res, desde=desde, hasta=hasta,
                           deps=deps, dep=dep, rangos=rangos)


@app.route("/asistencia/excel")
def asistencia_excel():
    desde, hasta = _rango()
    dep = request.args.get("dep", "")
    dias, res = asistencia.reporte(desde, hasta, int(dep) if dep else None)
    datos = reportes.excel(res, dias, f"Asistencia del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")
    return _archivo(datos, f"asistencia_{desde}_{hasta}.xlsx")


def _archivo(datos, nombre, en_linea=False):
    tipo = "application/pdf" if nombre.endswith(".pdf") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return send_file(io.BytesIO(datos), mimetype=tipo, download_name=nombre, as_attachment=not en_linea)


# ---------------------------------------------------------------- reportes
@app.route("/reportes")
def reportes_vista():
    with db.db() as con:
        emps = con.execute("""SELECT id, numero, nombre, apellidos, activo, fecha_ingreso FROM empleados
                              ORDER BY activo DESC, CAST(numero AS INTEGER), numero""").fetchall()
        deps = con.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
    hoy = date.today()
    return render_template("reportes.html", emps=emps, deps=deps,
                           mes=hoy.strftime("%Y-%m"), sel=request.args.get("empleado", ""))


@app.route("/reportes/descargar")
def reportes_descargar():
    a = request.args
    tipo, formato = a.get("tipo", "general"), a.get("formato", "pdf")
    dep = int(a["dep"]) if a.get("dep") else None
    dep_nombre = ""
    if dep:
        with db.db() as con:
            fila = con.execute("SELECT nombre FROM departamentos WHERE id=?", (dep,)).fetchone()
            dep_nombre = fila["nombre"] if fila else ""
    numeros = []
    emp_txt = ""
    if tipo in ("empleado", "historial", "checadas"):
        with db.db() as con:
            if a.get("empleado") in ("", "todos", None):
                numeros = [r["numero"] for r in con.execute(
                    "SELECT numero FROM empleados WHERE activo=1" + (" AND departamento_id=?" if dep else "") +
                    " ORDER BY CAST(numero AS INTEGER), numero", (dep,) if dep else ())]
                emp_txt = dep_nombre or "todos"
            else:
                e = con.execute("SELECT numero, nombre, apellidos FROM empleados WHERE id=?",
                                (a.get("empleado"),)).fetchone()
                if e:
                    numeros, emp_txt = [e["numero"]], f"{e['nombre']} {e['apellidos']}"
    desde, hasta, etiqueta = reportes.periodo(a.get("periodo", "mes"), a.get("mes"), a.get("desde"), a.get("hasta"))
    base = reportes.nombre_archivo(tipo, emp_txt, desde, hasta)
    try:
        if formato == "excel":
            if tipo == "directorio":
                tipo = "general"
            if tipo in ("empleado", "historial", "checadas"):
                res = []
                for n in numeros:
                    res += asistencia.reporte(desde, hasta, numero=n, solo_activos=False)[1]
                dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
            else:
                dias, res = asistencia.reporte(desde, hasta, dep)
            if tipo == "checadas":
                return _archivo(reportes.excel_checadas(res, etiqueta), base + ".xlsx")
            return _archivo(reportes.excel(res, dias, etiqueta), base + ".xlsx")
        if tipo == "checadas":
            res = []
            for n in numeros:
                res += asistencia.reporte(desde, hasta, numero=n, solo_activos=False)[1]
            datos = reportes.pdf_checadas(res, desde, hasta)
        elif tipo in ("empleado", "historial"):
            datos = reportes.pdf_empleados(numeros, desde, hasta, etiqueta, completo=(tipo == "historial"))
        elif tipo == "incidencias":
            datos = reportes.pdf_incidencias(desde, hasta, etiqueta, dep, dep_nombre)
        elif tipo == "directorio":
            datos = reportes.pdf_directorio(dep, dep_nombre)
            base = reportes.nombre_archivo("directorio", dep_nombre)
        else:
            datos = reportes.pdf_general(desde, hasta, etiqueta, dep, dep_nombre)
        return _archivo(datos, base + ".pdf", en_linea=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f"No se pudo generar el reporte: {e}", "error")
        return redirect(url_for("reportes_vista"))


# ---------------------------------------------------------------- reloj
def _pantalla_reloj(info=None):
    with db.db() as con:
        bit = con.execute("SELECT * FROM bitacora ORDER BY id DESC LIMIT 25").fetchall()
        n = {k: con.execute(q).fetchone()[0] for k, q in {
            "empleados": "SELECT COUNT(*) FROM empleados WHERE activo=1",
            "huellas": "SELECT COUNT(*) FROM huellas",
            "con_huella": "SELECT COUNT(DISTINCT numero) FROM huellas",
            "checadas": "SELECT COUNT(*) FROM checadas"}.items()}
    cfg = {k: db.cfg(k) for k in ("reloj_ip", "reloj_puerto", "reloj_password", "reloj_udp", "sync_minutos", "ajustar_hora")}
    return render_template("reloj.html", bit=bit, n=n, cfg=cfg, info=info)


@app.route("/reloj")
def reloj_vista():
    return _pantalla_reloj()


@app.route("/reloj/config", methods=["POST"])
def reloj_config():
    db.set_cfg(reloj_ip=request.form.get("reloj_ip", "").strip(),
               reloj_puerto=request.form.get("reloj_puerto", "4370").strip() or "4370",
               reloj_password=request.form.get("reloj_password", "0").strip() or "0",
               reloj_udp="1" if request.form.get("reloj_udp") else "0",
               sync_minutos=request.form.get("sync_minutos", "2").strip() or "2",
               ajustar_hora="1" if request.form.get("ajustar_hora") else "0")
    db.log(f"Cambió la conexión del reloj (IP {db.cfg('reloj_ip')}, puerto {db.cfg('reloj_puerto')})")
    flash("Configuración guardada.", "ok")
    return redirect(url_for("reloj_vista"))


@app.route("/reloj/<accion>", methods=["POST"])
def reloj_accion(accion):
    def activos():
        with db.db() as con:
            return [dict(r) for r in con.execute("SELECT * FROM empleados WHERE activo=1")]

    textos = {"checadas": "Leyó las checadas del reloj", "hora": "Ajustó la hora del reloj",
              "enviar_todos": "Envió todos los empleados al reloj", "respaldar": "Respaldó las huellas del reloj",
              "restaurar_todos": "Cargó todas las huellas respaldadas al reloj",
              "traer_usuarios": "Trajo los usuarios del reloj"}
    if accion in textos:
        db.log(textos[accion])
    if accion == "probar":
        try:
            info = reloj.info()
            db.set_cfg(ultimo_error="", ultima_sync_ok=db.cfg("ultima_sync_ok") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            flash("Conexión correcta con el reloj.", "ok")
            return _pantalla_reloj(info)
        except reloj.RelojError as e:
            db.set_cfg(ultimo_error=str(e))
            flash(str(e), "error")
    elif accion == "checadas":
        _accion_reloj(reloj.sincronizar, "Listo: {r} checadas nuevas.")
    elif accion == "hora":
        _accion_reloj(reloj.ajustar_hora, "La hora del reloj quedó igual a la de esta computadora.")
    elif accion == "enviar_todos":
        _accion_reloj(lambda: reloj.enviar_empleados(activos()), "{r} empleados enviados/actualizados en el reloj.")
    elif accion == "respaldar":
        _accion_reloj(reloj.respaldar_huellas, "{r} huellas respaldadas en esta computadora.")
    elif accion == "restaurar_todos":
        _accion_reloj(lambda: reloj.restaurar_huellas(activos()), "{r} huellas cargadas al reloj.")
    elif accion == "traer_usuarios":
        def traer():
            nuevos = 0
            with db.db() as con:
                for numero, nombre in reloj.traer_usuarios():
                    cur = con.execute("INSERT OR IGNORE INTO empleados (numero, nombre) VALUES (?,?)",
                                      (numero, (nombre or f"EMPLEADO {numero}").upper()))
                    nuevos += cur.rowcount
            return nuevos
        _accion_reloj(traer, "{r} empleados nuevos traídos del reloj (complétalos en su ficha).")
    return redirect(url_for("reloj_vista"))


# ---------------------------------------------------------------- horarios
@app.route("/horarios")
def horarios_vista():
    hs = asistencia.horarios()
    with db.db() as con:
        deps = [dict(d) for d in con.execute("""SELECT d.*, (SELECT COUNT(*) FROM empleados e
                    WHERE e.departamento_id=d.id AND e.activo=1) AS n FROM departamentos d ORDER BY nombre""")]
        individuales = {r["horario_id"]: r["n"] for r in con.execute(
            "SELECT horario_id, COUNT(*) AS n FROM empleados WHERE horario_id IS NOT NULL AND activo=1 GROUP BY horario_id")}
    sel = request.args.get("id", "")
    actual = None
    if sel == "nuevo":
        actual = asistencia.preparar_horario({"id": None, "nombre": "", "dias": db.HORARIO_DEFAULT, "tolerancia": 5,
                                              "comida": 60, "primera_ultima": 0, "tiempo_extra": 0})
    elif sel.isdigit() and int(sel) in hs:
        actual = hs[int(sel)]
    elif hs:
        actual = hs[min(hs)]
    for h in hs.values():
        h["deps"] = [d for d in deps if d["horario_id"] == h["id"]]
        h["personas"] = sum(d["n"] for d in h["deps"]) + individuales.get(h["id"], 0)
    return render_template("horarios.html", hs=list(hs.values()), actual=actual, deps=deps)


@app.route("/horarios/guardar", methods=["POST"])
def horarios_guardar():
    f = request.form
    dias = {}
    for i in range(7):
        tipo = f.get(f"tipo{i}", "descanso")
        if tipo == "fijo" and f.get(f"e{i}") and f.get(f"s{i}"):
            dias[str(i)] = {"tipo": "fijo", "entrada": f[f"e{i}"], "salida": f[f"s{i}"]}
        elif tipo == "flexible":
            try:
                minutos = round(float((f.get(f"h{i}") or "0").replace(",", ".")) * 60)
            except ValueError:
                minutos = 0
            dias[str(i)] = {"tipo": "flexible", "minutos": minutos} if minutos > 0 else None
            if dias[str(i)] and f.get(f"ef{i}"):
                dias[str(i)]["entrada"] = f[f"ef{i}"]
        else:
            dias[str(i)] = None
    datos = (f.get("nombre", "").strip() or "Horario", json.dumps(dias), int(f.get("tolerancia") or 0),
             int(f.get("comida") or 0), 1 if f.get("primera_ultima") else 0, 1 if f.get("tiempo_extra") else 0)
    with db.db() as con:
        if f.get("id"):
            id_ = int(f["id"])
            con.execute("UPDATE horarios SET nombre=?, dias=?, tolerancia=?, comida=?, primera_ultima=?, tiempo_extra=? "
                        "WHERE id=?", datos + (id_,))
        else:
            id_ = con.execute("INSERT INTO horarios (nombre, dias, tolerancia, comida, primera_ultima, tiempo_extra) "
                              "VALUES (?,?,?,?,?,?)", datos).lastrowid
        marcados = {int(x) for x in f.getlist("deps")}
        for d in con.execute("SELECT id, horario_id FROM departamentos").fetchall():
            if d["id"] in marcados:
                con.execute("UPDATE departamentos SET horario_id=? WHERE id=?", (id_, d["id"]))
            elif d["horario_id"] == id_:
                con.execute("UPDATE departamentos SET horario_id=NULL WHERE id=?", (d["id"],))
    db.log(f"{'Modificó' if f.get('id') else 'Creó'} el horario \"{datos[0]}\" (tolerancia {datos[2]} min, comida {datos[3]} min)")
    flash("Horario guardado.", "ok")
    return redirect(url_for("horarios_vista", id=id_))


@app.route("/horarios/<int:id_>/borrar", methods=["POST"])
def horarios_borrar(id_):
    with db.db() as con:
        if con.execute("SELECT COUNT(*) FROM horarios").fetchone()[0] <= 1:
            flash("Debe quedar al menos un horario.", "error")
            return redirect(url_for("horarios_vista", id=id_))
        h = con.execute("SELECT nombre FROM horarios WHERE id=?", (id_,)).fetchone()
        con.execute("UPDATE departamentos SET horario_id=NULL WHERE horario_id=?", (id_,))
        con.execute("UPDATE empleados SET horario_id=NULL WHERE horario_id=?", (id_,))
        con.execute("DELETE FROM horarios WHERE id=?", (id_,))
    if h:
        db.log(f"Eliminó el horario \"{h['nombre']}\"")
    flash("Horario eliminado. Quienes lo usaban toman el primer horario de la lista.", "ok")
    return redirect(url_for("horarios_vista"))


# ---------------------------------------------------------------- ajustes
@app.route("/ajustes")
def ajustes():
    with db.db() as con:
        hors = con.execute("SELECT id, nombre FROM horarios ORDER BY nombre").fetchall()
        deps = con.execute("""SELECT d.*, (SELECT COUNT(*) FROM empleados e WHERE e.departamento_id=d.id AND e.activo=1) AS n
                              FROM departamentos d ORDER BY nombre""").fetchall()
        usuarios = con.execute("SELECT id, usuario, nombre, activo, ultimo_acceso FROM usuarios "
                               "ORDER BY activo DESC, usuario").fetchall()
        anio = request.args.get("anio", date.today().year, type=int)
        festivos = [dict(f, dia=asistencia.DIAS[datetime.strptime(f["fecha"], "%Y-%m-%d").weekday()])
                    for f in con.execute("SELECT * FROM festivos WHERE fecha LIKE ? ORDER BY fecha", (f"{anio}-%",))]
        primero = con.execute("SELECT MIN(substr(fecha,1,4)) FROM festivos").fetchone()[0]
    este = date.today().year
    anios = list(range(min(int(primero or este), anio, este), max(anio, este + 1) + 1))
    return render_template("ajustes.html", hors=hors, deps=deps, usuarios=usuarios,
                           min_contrasena=MIN_CONTRASENA, festivos=festivos, anio=anio, anios=anios,
                           respaldos=_respaldos_guardados())


@app.route("/ajustes/usuario", methods=["POST"])
def ajustes_usuario_nuevo():
    usuario, nombre = request.form.get("usuario", "").strip(), request.form.get("nombre", "").strip()
    error = _validar_usuario_nuevo(usuario, request.form.get("contrasena", ""), request.form.get("contrasena2", ""))
    if error:
        flash(error, "error")
    else:
        db.crear_usuario(usuario, request.form["contrasena"], nombre)
        db.log(f"{g.usuario['usuario']} creó el usuario {usuario}")
        flash(f"Usuario {usuario} creado.", "ok")
    return redirect(url_for("ajustes") + "#usuarios")


@app.route("/ajustes/usuario/<int:id_>", methods=["POST"])
def ajustes_usuario(id_):
    with db.db() as con:
        u = con.execute("SELECT * FROM usuarios WHERE id=?", (id_,)).fetchone()
        activos = con.execute("SELECT COUNT(*) FROM usuarios WHERE activo=1").fetchone()[0]
    if not u:
        abort(404)
    accion = request.form.get("accion")
    if accion == "contrasena":
        c1, c2 = request.form.get("contrasena", ""), request.form.get("contrasena2", "")
        if len(c1) < MIN_CONTRASENA:
            flash(f"La contraseña debe tener al menos {MIN_CONTRASENA} caracteres.", "error")
        elif c1 != c2:
            flash("Las contraseñas no coinciden.", "error")
        else:
            db.cambiar_contrasena(id_, c1)
            db.log(f"{g.usuario['usuario']} cambió la contraseña de {u['usuario']}")
            flash(f"Contraseña de {u['usuario']} cambiada.", "ok")
    elif accion in ("desactivar", "activar"):
        if accion == "desactivar" and id_ == g.usuario["id"]:
            flash("No puedes desactivar tu propio usuario.", "error")
        elif accion == "desactivar" and activos <= 1:
            flash("Debe quedar al menos un usuario activo.", "error")
        else:
            with db.db() as con:
                con.execute("UPDATE usuarios SET activo=? WHERE id=?", (1 if accion == "activar" else 0, id_))
            db.log(f"{g.usuario['usuario']} {'activó' if accion == 'activar' else 'desactivó'} al usuario {u['usuario']}")
            flash(f"Usuario {u['usuario']} {'activado' if accion == 'activar' else 'desactivado'}.", "ok")
    return redirect(url_for("ajustes") + "#usuarios")


@app.route("/ajustes/empresa", methods=["POST"])
def ajustes_empresa():
    db.set_cfg(empresa=request.form.get("empresa", "").strip() or "Mi empresa")
    db.log(f"Cambió el nombre de la empresa a \"{db.cfg('empresa')}\"")
    flash("Guardado.", "ok")
    return redirect(url_for("ajustes"))


@app.route("/ajustes/departamento", methods=["POST"])
def ajustes_departamento():
    id_, nombre = request.form.get("id"), request.form.get("nombre", "").strip().upper()
    horario = request.form.get("horario_id") or None
    if request.form.get("borrar") and id_:
        with db.db() as con:
            con.execute("UPDATE empleados SET departamento_id=NULL WHERE departamento_id=?", (id_,))
            con.execute("DELETE FROM departamentos WHERE id=?", (id_,))
        db.log(f"Eliminó el departamento {nombre}")
        flash("Departamento eliminado.", "ok")
    elif nombre:
        try:
            with db.db() as con:
                if id_:
                    con.execute("UPDATE departamentos SET nombre=?, horario_id=? WHERE id=?", (nombre, horario, id_))
                else:
                    con.execute("INSERT INTO departamentos (nombre, horario_id) VALUES (?,?)", (nombre, horario))
            db.log(f"{'Modificó' if id_ else 'Creó'} el departamento {nombre}")
            flash("Departamento guardado.", "ok")
        except Exception:
            flash("Ya existe un departamento con ese nombre.", "error")
    return redirect(url_for("ajustes") + "#departamentos")


@app.route("/ajustes/importar", methods=["POST"])
def ajustes_importar():
    import importar_zktime
    f = request.files.get("archivo")
    if not f or not f.filename:
        flash("Elige el archivo .db del respaldo.", "error")
        return redirect(url_for("ajustes") + "#importar")
    ruta = os.path.join(db.DATA, "_importar_tmp.db")
    f.save(ruta)
    try:
        r = importar_zktime.importar(ruta)
        flash(f"Importado: {r['empleados']} empleados, {r['departamentos']} departamentos, "
              f"{r.get('horarios', 0)} horarios, {r['checadas']} checadas y {r['huellas']} huellas.", "ok")
    except Exception as e:
        flash(f"No se pudo importar: {e}", "error")
    finally:
        os.remove(ruta)
    return redirect(request.form.get("volver") or (url_for("ajustes") + "#importar"))


# ---------------------------------------------------------------- respaldo y restauración
RESPALDOS = os.path.join(db.DATA, "respaldos")  # copias automáticas antes de restaurar (para poder deshacer)


def _crear_respaldo(destino):
    """Escribe en destino (ruta o archivo abierto) un .zip con la base de datos, fotos y documentos."""
    import sqlite3
    tmp = os.path.join(db.DATA, f"_respaldo_tmp_{threading.get_ident()}.db")
    src, dst = sqlite3.connect(db.DB_PATH), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    try:
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, "datos/checador.db")
            for carpeta in (db.FOTOS, db.DOCS):
                for raiz, _, archivos in os.walk(carpeta):
                    if os.path.basename(raiz) == "mini":
                        continue
                    for a in archivos:
                        ruta = os.path.join(raiz, a)
                        z.write(ruta, "datos/" + os.path.relpath(ruta, db.DATA).replace(os.sep, "/"))
    finally:
        os.remove(tmp)


@app.route("/ajustes/respaldo")
def respaldo():
    buf = io.BytesIO()
    _crear_respaldo(buf)
    buf.seek(0)
    db.log("Descargó un respaldo completo")
    return send_file(buf, as_attachment=True, download_name=f"respaldo_checador_{date.today()}.zip",
                     mimetype="application/zip")


def _respaldos_guardados():
    if not os.path.isdir(RESPALDOS):
        return []
    lista = []
    for a in sorted(os.listdir(RESPALDOS), reverse=True):
        ruta = os.path.join(RESPALDOS, a)
        if a.endswith(".zip") and os.path.isfile(ruta):
            lista.append({"archivo": a, "tamano": os.path.getsize(ruta),
                          "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d %H:%M")})
    return lista


@app.route("/ajustes/respaldos/<nombre>")
def respaldo_guardado(nombre):
    if nombre not in {r["archivo"] for r in _respaldos_guardados()}:
        abort(404)
    return send_from_directory(RESPALDOS, nombre, as_attachment=True)


def _restaurar_desde(ruta_zip):
    """Revisa el .zip, guarda una copia de lo actual y reemplaza base de datos, fotos y documentos."""
    import shutil
    import sqlite3
    tmp_db = os.path.join(db.DATA, "_restaurar_tmp.db")
    try:
        z = zipfile.ZipFile(ruta_zip)
    except zipfile.BadZipFile:
        raise ValueError("Ese archivo no es un respaldo de Checador. Usa el .zip que se descarga en "
                         "Ajustes › Descargar respaldo completo.")
    try:
        with z:
            if "datos/checador.db" not in z.namelist():
                raise ValueError("Ese .zip no es un respaldo de Checador (no trae datos/checador.db).")
            with z.open("datos/checador.db") as origen, open(tmp_db, "wb") as copia:
                shutil.copyfileobj(origen, copia)
            con = sqlite3.connect(tmp_db)
            try:
                try:
                    integro = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                except sqlite3.DatabaseError:
                    integro, tablas = False, set()
                if not integro or not {"empleados", "checadas", "config"} <= tablas:
                    raise ValueError("El respaldo está dañado o incompleto; no se cambió nada.")
                res = {"empleados": con.execute("SELECT COUNT(*) FROM empleados").fetchone()[0],
                       "checadas": con.execute("SELECT COUNT(*) FROM checadas").fetchone()[0]}
            finally:
                con.close()

            # 1) copia de seguridad de lo que hay ahora, por si hay que deshacer
            os.makedirs(RESPALDOS, exist_ok=True)
            seguridad = f"antes_de_restaurar_{datetime.now():%Y-%m-%d_%H%M%S}.zip"
            _crear_respaldo(os.path.join(RESPALDOS, seguridad))

            # 2) base de datos (se pausa la lectura del reloj mientras tanto)
            with reloj._candado:
                src, dst = sqlite3.connect(tmp_db), db.conectar()
                try:
                    src.backup(dst)
                finally:
                    src.close()
                    dst.close()

            # 3) fotos y documentos (solo dentro de la carpeta de datos)
            base = os.path.realpath(db.DATA)
            archivos = 0
            for info in z.infolist():
                n = info.filename
                if info.is_dir() or not n.startswith(("datos/fotos/", "datos/documentos/")):
                    continue
                destino = os.path.realpath(os.path.join(db.DATA, *n[len("datos/"):].split("/")))
                if not destino.startswith(base + os.sep):
                    continue
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                with z.open(info) as origen, open(destino, "wb") as copia:
                    shutil.copyfileobj(origen, copia)
                archivos += 1
            shutil.rmtree(MINI, ignore_errors=True)  # las miniaturas se vuelven a crear solas
    finally:
        for extra in ("", "-wal", "-shm", "-journal"):
            if os.path.exists(tmp_db + extra):
                os.remove(tmp_db + extra)
    db.iniciar()  # si el respaldo es de una versión anterior, se actualiza
    res.update(archivos=archivos, seguridad=seguridad)
    return res


@app.route("/ajustes/restaurar", methods=["POST"])
def restaurar():
    volver = redirect(url_for("ajustes") + "#respaldo")
    quien = g.usuario["usuario"]
    if not db.verificar_usuario(quien, request.form.get("contrasena", "")):
        time.sleep(1)
        flash("Tu contraseña no es correcta. Se pide para confirmar que quieres restaurar.", "error")
        return volver
    guardado = request.form.get("guardado", "")
    tmp_zip = os.path.join(db.DATA, "_restaurar_tmp.zip")
    if guardado:
        if guardado not in {r["archivo"] for r in _respaldos_guardados()}:
            abort(404)
        import shutil
        shutil.copyfile(os.path.join(RESPALDOS, guardado), tmp_zip)
        nombre = guardado
    else:
        f = request.files.get("archivo")
        if not f or not f.filename:
            flash("Elige el archivo .zip del respaldo.", "error")
            return volver
        f.save(tmp_zip)
        nombre = f.filename
    try:
        r = _restaurar_desde(tmp_zip)
    except ValueError as e:
        flash(str(e), "error")
        return volver
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.log(f"Falló la restauración de {nombre}: {e}", "error", usuario=quien)
        flash(f"No se pudo restaurar: {e}", "error")
        return volver
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
    db.log(f"Restauró el respaldo {nombre}: {r['empleados']} empleados, {r['checadas']} checadas, "
           f"{r['archivos']} fotos/documentos. Lo anterior quedó guardado en {r['seguridad']}", usuario=quien)
    # Los usuarios y la clave de sesión ahora son los del respaldo: hay que volver a entrar
    app.secret_key = None
    session.clear()
    flash(f"Respaldo restaurado: {r['empleados']} empleados y {r['checadas']} checadas. Entra con un usuario "
          f"de ese respaldo. Lo que había antes quedó guardado en Ajustes › Respaldo por si necesitas regresar.", "ok")
    return redirect(url_for("login"))


# ---------------------------------------------------------------- días festivos
@app.route("/festivos", methods=["POST"])
def festivo_agregar():
    fecha, nombre = request.form.get("fecha", ""), request.form.get("nombre", "").strip()
    try:
        d = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        flash("Indica la fecha del día festivo.", "error")
        return redirect(url_for("ajustes") + "#festivos")
    nombre = nombre or "Día de descanso"
    try:
        with db.db() as con:
            con.execute("INSERT INTO festivos (fecha, nombre, oficial) VALUES (?,?,0)", (d.isoformat(), nombre))
    except Exception:
        flash("Ese día ya está como festivo.", "error")
        return redirect(url_for("ajustes", anio=d.year) + "#festivos")
    db.log(f"Agregó el día festivo {d:%d/%m/%Y} ({nombre})")
    flash(f"{nombre} agregado como día festivo. Ese día nadie tendrá falta.", "ok")
    return redirect(url_for("ajustes", anio=d.year) + "#festivos")


@app.route("/festivos/<int:id_>/borrar", methods=["POST"])
def festivo_borrar(id_):
    with db.db() as con:
        f = con.execute("SELECT * FROM festivos WHERE id=?", (id_,)).fetchone()
        if not f:
            abort(404)
        con.execute("DELETE FROM festivos WHERE id=?", (id_,))
    db.log(f"Quitó el día festivo {f['fecha']} ({f['nombre']})")
    flash("Día festivo quitado. Ese día vuelve a ser laboral.", "ok")
    return redirect(url_for("ajustes", anio=f["fecha"][:4]) + "#festivos")


@app.route("/festivos/oficiales", methods=["POST"])
def festivos_oficiales():
    anio = request.form.get("anio", type=int)
    if not anio or not 2000 <= anio <= 2100:
        abort(400)
    with db.db() as con:
        n = db.cargar_festivos_oficiales(con, anio)
        con.execute("INSERT OR REPLACE INTO config VALUES (?, '1')", (f"festivos_cargados_{anio}",))
    if n:
        db.log(f"Cargó {n} días festivos oficiales de {anio}")
    flash(f"{n} días festivos oficiales agregados." if n else "Los festivos oficiales de ese año ya estaban.", "ok")
    return redirect(url_for("ajustes", anio=anio) + "#festivos")


# ---------------------------------------------------------------- bitácora
POR_PAGINA = 200


def _filtros_bitacora():
    a = request.args
    hoy = date.today()
    f = {"desde": _fecha("desde", hoy - timedelta(days=30)), "hasta": _fecha("hasta", hoy),
         "usuario": a.get("usuario", ""), "tipo": a.get("tipo", ""), "q": a.get("q", "").strip()}
    sql = " WHERE fecha >= ? AND fecha < ?"
    args = [f["desde"].isoformat(), (f["hasta"] + timedelta(days=1)).isoformat()]
    if f["usuario"]:
        sql += " AND COALESCE(usuario, 'sistema') = ?"
        args.append(f["usuario"])
    if f["tipo"]:
        sql += " AND tipo = ?"
        args.append(f["tipo"])
    if f["q"]:
        sql += " AND mensaje LIKE ?"
        args.append(f"%{f['q']}%")
    return f, sql, args


@app.route("/bitacora")
def bitacora():
    f, sql, args = _filtros_bitacora()
    pagina = max(1, request.args.get("pagina", 1, type=int))
    with db.db() as con:
        total = con.execute("SELECT COUNT(*) FROM bitacora" + sql, args).fetchone()[0]
        filas = con.execute("SELECT * FROM bitacora" + sql + " ORDER BY id DESC LIMIT ? OFFSET ?",
                            args + [POR_PAGINA, (pagina - 1) * POR_PAGINA]).fetchall()
        usuarios = [r[0] for r in con.execute(
            "SELECT DISTINCT COALESCE(usuario, 'sistema') FROM bitacora ORDER BY 1")]
        mas_vieja = con.execute("SELECT MIN(fecha) FROM bitacora").fetchone()[0]
    paginas = max(1, -(-total // POR_PAGINA))
    args_url = {k: v for k, v in request.args.items() if k != "pagina"}
    return render_template("bitacora.html", filas=filas, f=f, total=total, pagina=pagina, paginas=paginas,
                           usuarios=usuarios, mas_vieja=mas_vieja, args_url=args_url,
                           limite_limpiar=date.today() - timedelta(days=90))


@app.route("/bitacora/excel")
def bitacora_excel():
    f, sql, args = _filtros_bitacora()
    with db.db() as con:
        filas = con.execute("SELECT * FROM bitacora" + sql + " ORDER BY id DESC", args).fetchall()
    wb, est = reportes._libro()
    ws = wb.active
    ws.title = "Bitácora"
    reportes._hoja(ws, est, f"{db.cfg('empresa')} — Bitácora del {f['desde']:%d/%m/%Y} al {f['hasta']:%d/%m/%Y}",
                   ["Fecha y hora", "Usuario", "Tipo", "Movimiento"],
                   [[b["fecha"], b["usuario"] or "sistema", "Error" if b["tipo"] == "error" else "Movimiento",
                     b["mensaje"]] for b in filas], [19, 16, 12, 110])
    buf = io.BytesIO()
    wb.save(buf)
    db.log(f"Exportó la bitácora a Excel ({len(filas)} registros)")
    return _archivo(buf.getvalue(), f"bitacora_{f['desde']}_{f['hasta']}.xlsx")


@app.route("/bitacora/limpiar", methods=["POST"])
def bitacora_limpiar():
    try:
        antes = datetime.strptime(request.form.get("antes", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Elige la fecha.", "error")
        return redirect(url_for("bitacora"))
    if antes > date.today() - timedelta(days=90):
        flash("Por seguridad siempre se conservan los últimos 3 meses de la bitácora.", "error")
        return redirect(url_for("bitacora"))
    with db.db() as con:
        n = con.execute("DELETE FROM bitacora WHERE fecha < ?", (antes.isoformat(),)).rowcount
    db.log(f"Borró {n} registros de la bitácora anteriores al {antes:%d/%m/%Y}")
    flash(f"Se borraron {n} registros anteriores al {antes:%d/%m/%Y}.", "ok")
    return redirect(url_for("bitacora"))


@app.errorhandler(413)
def muy_grande(_):
    flash("El archivo es demasiado grande (máximo 300 MB).", "error")
    return redirect(request.referrer or url_for("inicio"))


# ---------------------------------------------------------------- arranque
def crear_usuario_consola():
    """python app.py --nuevo-usuario : crea un usuario desde la terminal (sirve si se olvidó la contraseña)."""
    from getpass import getpass
    db.iniciar()
    print("\n  Crear usuario de Checador\n")
    usuario = input("  Usuario: ").strip()
    nombre = input("  Nombre (opcional): ").strip()
    contrasena = getpass("  Contraseña: ")
    error = _validar_usuario_nuevo(usuario, contrasena, getpass("  Repite la contraseña: "))
    if error:
        print(f"\n  {error}\n")
        sys.exit(1)
    db.crear_usuario(usuario, contrasena, nombre)
    db.log(f"Usuario creado desde la terminal: {usuario}")
    print(f"\n  Usuario {usuario} creado.\n")


def main():
    if "--nuevo-usuario" in sys.argv:
        return crear_usuario_consola()
    db.iniciar()
    if os.environ.get("CHECADOR_SIN_SYNC") != "1":
        reloj.iniciar_ciclo()
    red = os.environ.get("CHECADOR_RED") == "1" or "--red" in sys.argv
    host = "0.0.0.0" if red else "127.0.0.1"
    puerto = int(os.environ.get("CHECADOR_PUERTO", "8080"))
    url = f"http://localhost:{puerto}"
    print(f"\n  Checador Simple funcionando en {url}")
    if red:
        print("  (accesible desde otras computadoras de la red)")
    print("  Deja esta ventana abierta. Para cerrar el programa, ciérrala.\n")
    if "--sin-navegador" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=host, port=puerto, threads=8)
    except ImportError:
        app.run(host=host, port=puerto)


if __name__ == "__main__":
    main()
