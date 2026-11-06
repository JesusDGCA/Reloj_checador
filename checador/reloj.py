"""Comunicación con el reloj checador (protocolo ZKTeco, usado por el Steren CLK-960).

Cada operación abre la conexión, hace su trabajo y la cierra. Así el reloj
nunca se queda "ocupado" y sigue checando con normalidad.
Si la IP del reloj se configura como "simulado" se usa un reloj de práctica.
"""
import random
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import db

_candado = threading.Lock()  # una sola operación con el reloj a la vez


class RelojError(Exception):
    pass


# ---------------------------------------------------------------- conexión
@contextmanager
def conexion():
    ip = db.cfg("reloj_ip").strip()
    if ip.lower() == "simulado":
        with _candado:
            yield _SIMULADOR
        return
    try:
        from zk import ZK
    except ImportError:
        raise RelojError("Falta la librería pyzk (pip install pyzk)")
    zk = ZK(ip, port=int(db.cfg("reloj_puerto") or 4370), timeout=10,
            password=int(db.cfg("reloj_password") or 0),
            force_udp=db.cfg("reloj_udp") == "1", ommit_ping=True)
    with _candado:
        try:
            conn = zk.connect()
        except Exception as e:
            raise RelojError(f"No se pudo conectar al reloj en {ip}: {e}")
        try:
            yield conn
        except RelojError:
            raise
        except Exception as e:
            raise RelojError(f"El reloj respondió con un error: {e}")
        finally:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass


def _nombre_reloj(emp):
    """El reloj guarda máx. 24 caracteres y sin acentos se ve mejor."""
    import unicodedata
    n = f"{emp['nombre']} {emp['apellidos']}".strip().upper()
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    return n[:24]


# ---------------------------------------------------------------- operaciones
def info():
    with conexion() as c:
        c.read_sizes()
        return {
            "firmware": c.get_firmware_version(),
            "serie": c.get_serialnumber(),
            "plataforma": c.get_platform(),
            "hora": c.get_time().strftime("%Y-%m-%d %H:%M:%S"),
            "usuarios": c.users, "huellas": c.fingers, "checadas": c.records,
        }


def descargar_checadas():
    """Trae las checadas del reloj y guarda solo las nuevas. Regresa cuántas nuevas."""
    with conexion() as c:
        registros = c.get_attendance()
        hora_reloj = c.get_time()
        if db.cfg("ajustar_hora") == "1" and abs((hora_reloj - datetime.now()).total_seconds()) > 60:
            c.set_time(datetime.now())
            db.log(f"Hora del reloj corregida ({hora_reloj:%H:%M} → {datetime.now():%H:%M})")
    nuevas = 0
    with db.db() as con:
        for r in registros:
            cur = con.execute("INSERT OR IGNORE INTO checadas (numero, fecha_hora, origen) VALUES (?,?, 'reloj')",
                              (str(r.user_id), r.timestamp.strftime("%Y-%m-%d %H:%M:%S")))
            nuevas += cur.rowcount
    return nuevas


def ajustar_hora():
    with conexion() as c:
        c.set_time(datetime.now())


def _usuarios_por_numero(c):
    return {str(u.user_id): u for u in c.get_users()}


def enviar_empleados(empleados):
    """Da de alta / actualiza empleados en el reloj (conserva sus huellas)."""
    with conexion() as c:
        existentes = _usuarios_por_numero(c)
        siguiente = max([u.uid for u in existentes.values()] + [0]) + 1
        for emp in empleados:
            u = existentes.get(str(emp["numero"]))
            uid = u.uid if u else siguiente
            if not u:
                siguiente += 1
            c.set_user(uid=uid, name=_nombre_reloj(emp),
                       privilege=u.privilege if u else 0,
                       password=u.password if u else "",
                       group_id=u.group_id if u else "",
                       user_id=str(emp["numero"]), card=u.card if u else 0)
    return len(empleados)


def borrar_empleado(numero):
    with conexion() as c:
        u = _usuarios_por_numero(c).get(str(numero))
        if u:
            c.delete_user(uid=u.uid)
            return True
    return False


def traer_usuarios():
    """Lista de (numero, nombre) dados de alta en el reloj."""
    with conexion() as c:
        return [(str(u.user_id), u.name) for u in c.get_users()]


def respaldar_huellas():
    """Copia todas las huellas del reloj a la base local. Regresa cuántas."""
    with conexion() as c:
        por_uid = {u.uid: str(u.user_id) for u in c.get_users()}
        huellas = c.get_templates()
    n = 0
    with db.db() as con:
        for h in huellas:
            numero = por_uid.get(h.uid)
            if numero:
                con.execute("INSERT OR REPLACE INTO huellas (numero, dedo, plantilla, actualizado) "
                            "VALUES (?,?,?, datetime('now','localtime'))", (numero, h.fid, h.template))
                n += 1
    return n


def restaurar_huellas(empleados):
    """Sube al reloj las huellas respaldadas de los empleados indicados.
    Si el empleado no existe en el reloj, primero lo da de alta."""
    from zk.finger import Finger
    enviar_empleados(empleados)
    total = 0
    with conexion() as c:
        existentes = _usuarios_por_numero(c)
        with db.db() as con:
            for emp in empleados:
                u = existentes.get(str(emp["numero"]))
                filas = con.execute("SELECT dedo, plantilla FROM huellas WHERE numero=?",
                                    (str(emp["numero"]),)).fetchall()
                if not u or not filas:
                    continue
                dedos = [Finger(u.uid, f["dedo"], 1, bytes(f["plantilla"])) for f in filas]
                c.save_user_template(u, dedos)
                total += len(dedos)
    return total


# ---------------------------------------------------------------- sincronización automática
def sincronizar():
    """Lo que hace el ciclo automático: bajar checadas (y ajustar hora)."""
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        n = descargar_checadas()
        db.set_cfg(ultima_sync=ahora, ultima_sync_ok=ahora, ultimo_error="")
        if n:
            db.log(f"{n} checadas nuevas descargadas")
        return n
    except RelojError as e:
        db.set_cfg(ultima_sync=ahora, ultimo_error=str(e))
        raise


def iniciar_ciclo():
    def ciclo():
        import time
        while True:
            try:
                sincronizar()
            except Exception:
                pass
            minutos = max(1, int(db.cfg("sync_minutos") or 2))
            time.sleep(minutos * 60)
    threading.Thread(target=ciclo, daemon=True, name="sync-reloj").start()


# ---------------------------------------------------------------- reloj simulado (para practicar)
class _Usuario:
    def __init__(self, uid, name, user_id, privilege=0, password="", group_id="", card=0):
        self.uid, self.name, self.user_id = uid, name, user_id
        self.privilege, self.password, self.group_id, self.card = privilege, password, group_id, card


class _Registro:
    def __init__(self, user_id, ts):
        self.user_id, self.timestamp = user_id, ts


class _RelojSimulado:
    def __init__(self):
        self.usuarios, self.huellas, self.registros = {}, {}, []
        self.desfase = timedelta(minutes=7)

    users = property(lambda s: len(s.usuarios))
    fingers = property(lambda s: len(s.huellas))
    records = property(lambda s: len(s.registros))

    def read_sizes(self): pass
    def enable_device(self): pass
    def get_firmware_version(self): return "Ver 6.60 (simulado)"
    def get_serialnumber(self): return "SIMULADO-0001"
    def get_platform(self): return "ZMM220_TFT"
    def get_time(self): return datetime.now() + self.desfase
    def set_time(self, t): self.desfase = timedelta(0)
    def _cargar_de_la_base(self):
        """Si el reloj de práctica está vacío, toma los empleados activos (para que la demo funcione sola)."""
        if self.usuarios:
            return
        with db.db() as con:
            for i, e in enumerate(con.execute("SELECT numero, nombre, apellidos FROM empleados WHERE activo=1 "
                                              "ORDER BY CAST(numero AS INTEGER)"), 1):
                self.usuarios[i] = _Usuario(i, f"{e['nombre']} {e['apellidos']}"[:24], e["numero"])

    def get_users(self):
        self._cargar_de_la_base()
        return list(self.usuarios.values())
    def delete_user(self, uid): self.usuarios.pop(uid, None)

    def set_user(self, uid, name, privilege=0, password="", group_id="", user_id="", card=0):
        self.usuarios[uid] = _Usuario(uid, name, user_id, privilege, password, group_id, card)

    def get_templates(self):
        from zk.finger import Finger
        return [Finger(uid, fid, 1, t) for (uid, fid), t in self.huellas.items()]

    def save_user_template(self, user, fingers):
        for f in fingers:
            self.huellas[(user.uid, f.fid)] = f.template

    def get_attendance(self):
        # cada vez que se consulta, alguien "checa"
        self._cargar_de_la_base()
        if self.usuarios and random.random() < 0.7:
            u = random.choice(list(self.usuarios.values()))
            self.registros.append(_Registro(u.user_id, datetime.now().replace(microsecond=0)))
        return list(self.registros)


_SIMULADOR = _RelojSimulado()
