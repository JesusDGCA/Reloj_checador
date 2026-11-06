"""Base de datos local (SQLite). Todo vive en la carpeta data/."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("CHECADOR_DATOS") or os.path.join(BASE, "data")
FOTOS = os.path.join(DATA, "fotos")
DOCS = os.path.join(DATA, "documentos")
DB_PATH = os.path.join(DATA, "checador.db")

_F = {"tipo": "fijo", "entrada": "08:00", "salida": "18:00"}
HORARIO_DEFAULT = {  # lunes=0 ... domingo=6 ; None = descanso
    "0": _F, "1": _F, "2": _F, "3": _F, "4": _F,
    "5": {"tipo": "fijo", "entrada": "08:00", "salida": "14:00"}, "6": None,
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT);

CREATE TABLE IF NOT EXISTS horarios (
    id INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
    dias TEXT NOT NULL,              -- JSON {"0": {"tipo":"fijo","entrada":"08:00","salida":"18:00"} | {"tipo":"flexible","minutos":600} | null}
    tolerancia INTEGER DEFAULT 5,    -- minutos antes de contar retardo
    comida INTEGER DEFAULT 60,       -- minutos de comida si solo hay 2 checadas (horario fijo)
    primera_ultima INTEGER DEFAULT 0,-- 1 = solo primera checada como entrada y última como salida
    tiempo_extra INTEGER DEFAULT 0   -- 1 = contar horas extra
);

CREATE TABLE IF NOT EXISTS departamentos (
    id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
    horario_id INTEGER REFERENCES horarios(id)
);

CREATE TABLE IF NOT EXISTS empleados (
    id INTEGER PRIMARY KEY,
    numero TEXT NOT NULL UNIQUE,     -- el No. de usuario en el reloj
    nombre TEXT NOT NULL, apellidos TEXT DEFAULT '',
    departamento_id INTEGER REFERENCES departamentos(id),
    horario_id INTEGER REFERENCES horarios(id),  -- vacío = el del departamento
    puesto TEXT DEFAULT '', telefono TEXT DEFAULT '', email TEXT DEFAULT '',
    curp TEXT DEFAULT '', rfc TEXT DEFAULT '', nss TEXT DEFAULT '',
    direccion TEXT DEFAULT '', fecha_nacimiento TEXT DEFAULT '',
    fecha_ingreso TEXT DEFAULT '', fecha_baja TEXT DEFAULT '',
    salario TEXT DEFAULT '',
    contacto_emergencia TEXT DEFAULT '', tel_emergencia TEXT DEFAULT '',
    notas TEXT DEFAULT '', foto TEXT DEFAULT '',
    activo INTEGER DEFAULT 1,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,              -- contrato | identificacion | comprobante | otro
    nombre TEXT NOT NULL,            -- nombre original del archivo
    archivo TEXT NOT NULL,           -- nombre guardado en data/documentos
    tamano INTEGER DEFAULT 0,
    inicio TEXT DEFAULT '', vence TEXT DEFAULT '',  -- vigencia (contratos)
    notas TEXT DEFAULT '',
    subido TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS checadas (
    id INTEGER PRIMARY KEY,
    numero TEXT NOT NULL,
    fecha_hora TEXT NOT NULL,        -- 'YYYY-MM-DD HH:MM:SS'
    origen TEXT DEFAULT 'reloj',     -- reloj | importado | manual
    nota TEXT DEFAULT '',
    UNIQUE(numero, fecha_hora)
);
CREATE INDEX IF NOT EXISTS ix_checadas_fecha ON checadas(fecha_hora);

CREATE TABLE IF NOT EXISTS huellas (
    numero TEXT NOT NULL, dedo INTEGER NOT NULL,
    plantilla BLOB NOT NULL,
    actualizado TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (numero, dedo)
);

CREATE TABLE IF NOT EXISTS usuarios (  -- personas que pueden entrar al programa
    id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nombre TEXT DEFAULT '',
    hash TEXT NOT NULL,              -- contraseña cifrada (nunca se guarda en texto plano)
    activo INTEGER DEFAULT 1,
    ultimo_acceso TEXT DEFAULT '',
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS bitacora (
    id INTEGER PRIMARY KEY, fecha TEXT DEFAULT (datetime('now','localtime')),
    tipo TEXT DEFAULT 'info', mensaje TEXT,
    usuario TEXT DEFAULT 'sistema'   -- quién lo hizo ('sistema' = el programa solo, p. ej. leer el reloj)
);
CREATE INDEX IF NOT EXISTS ix_bitacora_fecha ON bitacora(fecha);

CREATE TABLE IF NOT EXISTS festivos (  -- días de descanso para todos: no cuentan como falta
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL UNIQUE,      -- 'YYYY-MM-DD'
    nombre TEXT NOT NULL,
    oficial INTEGER DEFAULT 0        -- 1 = de la Ley Federal del Trabajo (art. 74), 0 = agregado por la empresa
);

CREATE TABLE IF NOT EXISTS justificaciones (  -- vacaciones, incapacidades, permisos: la falta no cuenta
    id INTEGER PRIMARY KEY,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
    desde TEXT NOT NULL, hasta TEXT NOT NULL,   -- 'YYYY-MM-DD', ambos incluidos
    tipo TEXT NOT NULL,
    nota TEXT DEFAULT '',
    usuario TEXT DEFAULT '',         -- quién la registró
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_justificaciones_emp ON justificaciones(empleado_id, desde);
"""

TIPOS_JUSTIFICACION = {
    "vacaciones": "Vacaciones",
    "incapacidad": "Incapacidad (IMSS)",
    "permiso_goce": "Permiso con goce de sueldo",
    "permiso_sin_goce": "Permiso sin goce de sueldo",
    "comision": "Comisión / trabajo fuera",
    "otro": "Otro motivo",
}
# Abreviatura para el cuadro de asistencia
ABREV_JUSTIFICACION = {"vacaciones": "Vac.", "incapacidad": "Incap.", "permiso_goce": "Permiso",
                       "permiso_sin_goce": "Permiso", "comision": "Comisión", "otro": "Justif."}

TIPOS_DOC = {"contrato": "Contrato", "identificacion": "Identificación (INE)",
             "comprobante": "Comprobante de domicilio", "acta": "Acta de nacimiento",
             "otro": "Otro documento"}

CONFIG_DEFAULT = {
    "empresa": "Mi empresa",
    "reloj_ip": "192.168.1.64",
    "reloj_puerto": "4370",
    "reloj_password": "0",
    "reloj_udp": "0",
    "sync_minutos": "2",
    "ajustar_hora": "1",
    "ultima_sync": "",
    "ultima_sync_ok": "",
    "ultimo_error": "",
}


def conectar():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


@contextmanager
def db():
    con = conectar()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar():
    for d in (DATA, FOTOS, DOCS):
        os.makedirs(d, exist_ok=True)
    with db() as con:
        con.executescript(ESQUEMA)
        # migración de versiones anteriores
        cols = {r[1] for r in con.execute("PRAGMA table_info(horarios)")}
        for col in ("primera_ultima", "tiempo_extra"):
            if col not in cols:
                con.execute(f"ALTER TABLE horarios ADD COLUMN {col} INTEGER DEFAULT 0")
        if "usuario" not in {r[1] for r in con.execute("PRAGMA table_info(bitacora)")}:
            con.execute("ALTER TABLE bitacora ADD COLUMN usuario TEXT DEFAULT 'sistema'")
        for k, v in CONFIG_DEFAULT.items():
            con.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (k, v))
        if not con.execute("SELECT 1 FROM horarios").fetchone():
            con.execute("INSERT INTO horarios (nombre, dias, tolerancia, comida) VALUES (?,?,?,?)",
                        ("General", json.dumps(HORARIO_DEFAULT), 5, 60))
        # festivos oficiales: desde el año de la checada más antigua hasta el año que entra
        primera = con.execute("SELECT MIN(fecha_hora) FROM checadas").fetchone()[0]
        este = date.today().year
        for anio in range(min(int(primera[:4]) if primera else este, este), este + 2):
            _festivos_oficiales_si_faltan(con, anio)


# ---------------------------------------------------------------- días festivos
def _n_lunes(anio, mes, n):
    """El n-ésimo lunes del mes."""
    d = date(anio, mes, 1)
    d += timedelta(days=(0 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def festivos_oficiales(anio):
    """Días de descanso obligatorio de la Ley Federal del Trabajo, artículo 74."""
    lista = [
        (date(anio, 1, 1), "Año Nuevo"),
        (_n_lunes(anio, 2, 1), "Día de la Constitución"),
        (_n_lunes(anio, 3, 3), "Natalicio de Benito Juárez"),
        (date(anio, 5, 1), "Día del Trabajo"),
        (date(anio, 9, 16), "Día de la Independencia"),
        (_n_lunes(anio, 11, 3), "Revolución Mexicana"),
        (date(anio, 12, 25), "Navidad"),
    ]
    if anio >= 2024 and (anio - 2024) % 6 == 0:
        lista.append((date(anio, 10, 1), "Transmisión del Poder Ejecutivo Federal"))
    return sorted(lista)


def _festivos_oficiales_si_faltan(con, anio):
    """Carga los festivos oficiales de un año una sola vez (si después borras uno, no vuelve a aparecer)."""
    clave = f"festivos_cargados_{anio}"
    if con.execute("SELECT 1 FROM config WHERE clave=?", (clave,)).fetchone():
        return 0
    n = cargar_festivos_oficiales(con, anio)
    con.execute("INSERT OR REPLACE INTO config VALUES (?, '1')", (clave,))
    return n


def cargar_festivos_oficiales(con, anio):
    n = 0
    for f, nombre in festivos_oficiales(anio):
        n += con.execute("INSERT OR IGNORE INTO festivos (fecha, nombre, oficial) VALUES (?,?,1)",
                         (f.isoformat(), nombre)).rowcount
    return n


def clave_secreta():
    """Clave para firmar las sesiones. Se genera al azar una sola vez y se guarda en la base."""
    import secrets
    clave = cfg("clave_secreta")
    if not clave:
        clave = secrets.token_hex(32)
        with db() as con:
            con.execute("INSERT OR IGNORE INTO config VALUES ('clave_secreta', ?)", (clave,))
        clave = cfg("clave_secreta")
    return clave


# ---------------------------------------------------------------- usuarios
def hay_usuarios():
    with db() as con:
        return con.execute("SELECT 1 FROM usuarios WHERE activo=1").fetchone() is not None


def crear_usuario(usuario, contrasena, nombre=""):
    from werkzeug.security import generate_password_hash
    with db() as con:
        con.execute("INSERT INTO usuarios (usuario, nombre, hash) VALUES (?,?,?)",
                    (usuario.strip(), nombre.strip(), generate_password_hash(contrasena)))


def cambiar_contrasena(id_, contrasena):
    from werkzeug.security import generate_password_hash
    with db() as con:
        con.execute("UPDATE usuarios SET hash=? WHERE id=?", (generate_password_hash(contrasena), id_))


def verificar_usuario(usuario, contrasena):
    """Devuelve el usuario si la contraseña es correcta y está activo; si no, None."""
    from werkzeug.security import check_password_hash
    with db() as con:
        u = con.execute("SELECT * FROM usuarios WHERE usuario=? AND activo=1", (usuario.strip(),)).fetchone()
        if u and check_password_hash(u["hash"], contrasena):
            con.execute("UPDATE usuarios SET ultimo_acceso=datetime('now','localtime') WHERE id=?", (u["id"],))
            return dict(u)
    return None


def cfg(clave, default=""):
    with db() as con:
        r = con.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
    return r["valor"] if r else default


def set_cfg(**valores):
    with db() as con:
        for k, v in valores.items():
            con.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (k, str(v)))


def usuario_actual():
    """Nombre de usuario de quien está usando el programa, o 'sistema' si lo hace el programa solo."""
    try:
        from flask import g, has_request_context
        if has_request_context() and g.get("usuario"):
            return g.usuario["usuario"]
    except Exception:
        pass
    return "sistema"


MAX_BITACORA = 200_000  # suficiente para años; se puede limpiar a mano desde Bitácora


def log(mensaje, tipo="info", usuario=None):
    with db() as con:
        con.execute("INSERT INTO bitacora (tipo, mensaje, usuario) VALUES (?,?,?)",
                    (tipo, mensaje, usuario or usuario_actual()))
        con.execute("DELETE FROM bitacora WHERE id <= (SELECT MAX(id) - ? FROM bitacora)", (MAX_BITACORA,))
