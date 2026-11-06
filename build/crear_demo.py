"""Crea una base de DEMOSTRACIÓN con empresa y empleados ficticios (para enseñar Checador sin datos reales).

Uso:  python crear_demo.py CARPETA_DE_DATOS
Entra con  usuario: demo   contraseña: demo123
Usa el reloj de práctica ("simulado"): las checadas nuevas llegan solas cada minuto.
"""
import os
import random
import sys
from datetime import date, datetime, timedelta

destino = os.path.abspath(sys.argv[1])
if os.path.exists(os.path.join(destino, "checador.db")):
    sys.exit(f"Ya existe una base en {destino}; bórrala primero si quieres crearla de nuevo.")
os.environ["CHECADOR_DATOS"] = destino
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "checador"))

import asistencia  # noqa: E402
import db  # noqa: E402

random.seed(2026)
db.iniciar()
db.set_cfg(empresa="EMPRESA DEMOSTRACIÓN S.A. DE C.V.", reloj_ip="simulado", sync_minutos="1", ajustar_hora="1")
db.crear_usuario("demo", "demo123", "Usuario de demostración")
db.crear_usuario("rh", "rh12345", "Recursos Humanos")

with db.db() as con:
    general = con.execute("SELECT id FROM horarios ORDER BY id").fetchone()[0]
    con.execute("UPDATE horarios SET nombre='Planta', tiempo_extra=1 WHERE id=?", (general,))
    oficina_dias = {str(i): {"tipo": "fijo", "entrada": "09:00", "salida": "18:00"} for i in range(5)}
    oficina_dias.update({"5": None, "6": None})
    import json
    oficina = con.execute("INSERT INTO horarios (nombre, dias, tolerancia, comida, tiempo_extra) VALUES "
                          "('Oficina', ?, 10, 60, 0)", (json.dumps(oficina_dias),)).lastrowid
    deps = {}
    for nombre, hor in (("PRODUCCIÓN", general), ("ALMACÉN", general), ("ADMINISTRACIÓN", oficina), ("VENTAS", oficina)):
        deps[nombre] = con.execute("INSERT INTO departamentos (nombre, horario_id) VALUES (?,?)", (nombre, hor)).lastrowid

EMPLEADOS = [  # numero, nombre, apellidos, departamento, puesto, ingreso
    ("101", "MARÍA FERNANDA", "LÓPEZ RAMÍREZ", "ADMINISTRACIÓN", "GERENTE ADMINISTRATIVA", "2019-03-04"),
    ("102", "JOSÉ LUIS", "HERNÁNDEZ CRUZ", "PRODUCCIÓN", "SUPERVISOR DE PLANTA", "2018-07-16"),
    ("103", "ANA KAREN", "MARTÍNEZ SOTO", "VENTAS", "EJECUTIVA DE VENTAS", "2022-01-10"),
    ("104", "CARLOS ALBERTO", "GARCÍA MENDOZA", "PRODUCCIÓN", "OPERADOR", "2021-05-03"),
    ("105", "GUADALUPE", "TORRES VEGA", "PRODUCCIÓN", "OPERADORA", "2020-09-21"),
    ("106", "JUAN PABLO", "RAMOS ORTIZ", "ALMACÉN", "ALMACENISTA", "2023-02-13"),
    ("107", "DIANA LAURA", "FLORES AGUILAR", "ADMINISTRACIÓN", "AUXILIAR CONTABLE", "2024-04-01"),
    ("108", "MIGUEL ÁNGEL", "JIMÉNEZ RUIZ", "PRODUCCIÓN", "OPERADOR", "2022-11-07"),
    ("109", "SANDRA", "MORALES CASTILLO", "VENTAS", "VENDEDORA", "2023-08-14"),
    ("110", "RICARDO", "VÁZQUEZ NAVARRO", "ALMACÉN", "CHOFER", "2021-10-25"),
    ("111", "PATRICIA", "REYES DOMÍNGUEZ", "PRODUCCIÓN", "OPERADORA", "2024-06-17"),
    ("112", "FERNANDO", "GUTIÉRREZ SALAS", "PRODUCCIÓN", "MECÁNICO", "2019-12-02"),
    ("113", "ALEJANDRA", "CHÁVEZ ROJAS", "ADMINISTRACIÓN", "RECEPCIONISTA", "2025-01-20"),
    ("114", "OSCAR", "MENDOZA PÉREZ", "PRODUCCIÓN", "OPERADOR", "2025-03-10"),
    ("115", "LUCÍA", "SANTOS ÁVILA", "ALMACÉN", "AUXILIAR DE ALMACÉN", "2025-07-07"),
]
with db.db() as con:
    for n, nom, ape, dep, puesto, ingreso in EMPLEADOS:
        con.execute("""INSERT INTO empleados (numero, nombre, apellidos, departamento_id, puesto, telefono,
                       fecha_ingreso, salario) VALUES (?,?,?,?,?,?,?,?)""",
                    (n, nom, ape, deps[dep], puesto, f"55 {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
                     ingreso, str(random.choice([9500, 10500, 12000, 14500, 18000]))))
    # un empleado dado de baja (su historial se conserva)
    con.execute("""INSERT INTO empleados (numero, nombre, apellidos, departamento_id, puesto, fecha_ingreso,
                   fecha_baja, activo) VALUES ('116', 'ROBERTO', 'NÚÑEZ LARA', ?, 'OPERADOR', '2023-05-02', ?, 0)""",
                (deps["PRODUCCIÓN"], (date.today() - timedelta(days=20)).isoformat()))
    emps = [dict(r) for r in asistencia.empleados_con_horario(con, solo_activos=False)]
    for e in emps[:13]:  # casi todos con huella respaldada
        for dedo in (0, 1):
            con.execute("INSERT INTO huellas (numero, dedo, plantilla) VALUES (?,?,?)",
                        (e["numero"], dedo, os.urandom(512)))

hs = asistencia.horarios()
hoy = date.today()
ahora = datetime.now()
inicio = hoy - timedelta(days=60)
dias_habiles = [inicio + timedelta(days=i) for i in range((hoy - inicio).days)]
dias_habiles = [d for d in dias_habiles if d.weekday() < 5]

# ausencias justificadas (esos días no checan)
justif = {
    "105": ("vacaciones", dias_habiles[-15], dias_habiles[-11], "Primer periodo vacacional 2026"),
    "108": ("incapacidad", dias_habiles[-8], dias_habiles[-6], "Incapacidad IMSS folio 4581237"),
    "103": ("permiso_goce", dias_habiles[-3], dias_habiles[-3], "Trámite personal, autorizado por gerencia"),
    "112": ("comision", dias_habiles[-20], dias_habiles[-19], "Instalación de maquinaria con cliente"),
}
with db.db() as con:
    for e in emps:
        if e["numero"] in justif:
            t, d1, d2, nota = justif[e["numero"]]
            con.execute("INSERT INTO justificaciones (empleado_id, desde, hasta, tipo, nota, usuario) "
                        "VALUES (?,?,?,?,?, 'rh')", (e["id"], d1.isoformat(), d2.isoformat(), t, nota))
    festivos = {r["fecha"] for r in con.execute("SELECT fecha FROM festivos")}


def hm(texto, dia, delta=0):
    h, m = map(int, texto.split(":"))
    return datetime.combine(dia, datetime.min.time()) + timedelta(hours=h, minutes=m + delta)


checadas = []
# empleados "puntuales" y "con retardos" para que los reportes se vean variados
impuntuales = {"104", "110", "114"}
for e in emps:
    h = hs[e["horario_ef"]]
    baja = e["fecha_baja"] or "9999"
    for i in range((hoy - inicio).days + 1):
        dia = inicio + timedelta(days=i)
        plan = h["dias"].get(str(dia.weekday()))
        iso = dia.isoformat()
        if not plan or iso < e["fecha_ingreso"] or iso > baja:
            continue
        if iso in festivos and e["numero"] != "102":  # el supervisor fue a trabajar en festivo
            continue
        j = justif.get(e["numero"])
        if j and j[1] <= dia <= j[2]:
            continue
        if dia < hoy and random.random() < 0.025:  # falta sin justificar
            continue
        prob_retardo = 0.35 if e["numero"] in impuntuales else 0.05
        llegada = hm(plan["entrada"], dia, random.randint(6, 40) if random.random() < prob_retardo
                     else random.randint(-18, 3))
        if dia == hoy:
            if llegada <= ahora and random.random() < 0.85:
                checadas.append((e["numero"], llegada))
            continue
        salida = hm(plan["salida"], dia, random.randint(0, 15))
        if h["tiempo_extra"] and random.random() < 0.12:
            salida += timedelta(minutes=random.randint(60, 120))
        marcas = [llegada]
        if (hm(plan["salida"], dia) - hm(plan["entrada"], dia)).seconds > 7 * 3600:
            sale = hm("13:00" if plan["entrada"] < "09:00" else "14:00", dia, random.randint(-5, 10))
            marcas += [sale, sale + timedelta(minutes=random.randint(52, 66))]
        if random.random() > 0.02:  # a veces olvida checar la salida
            marcas.append(salida)
        checadas += [(e["numero"], m) for m in marcas]

with db.db() as con:
    con.executemany("INSERT OR IGNORE INTO checadas (numero, fecha_hora, origen) VALUES (?,?, 'reloj')",
                    [(n, m.strftime("%Y-%m-%d %H:%M:%S")) for n, m in checadas])
    # una checada agregada a mano, como ejemplo
    olvido = dias_habiles[-4]
    con.execute("INSERT OR IGNORE INTO checadas (numero, fecha_hora, origen, nota) VALUES ('106', ?, 'manual', ?)",
                (f"{olvido} 18:05:00", "Olvidó checar la salida; confirmado por su supervisor"))

# contratos (PDF de ejemplo): algunos por vencer, uno vencido, otros indefinidos y dos empleados sin contrato
from fpdf import FPDF  # noqa: E402

os.makedirs(db.DOCS, exist_ok=True)
vencimientos = {"103": 12, "109": 26, "113": -5, "114": 75, "115": 140}
with db.db() as con:
    for e in emps:
        if e["numero"] in ("111", "116"):
            continue
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, "CONTRATO INDIVIDUAL DE TRABAJO (EJEMPLO)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        texto = (f"Documento de demostracion para el empleado No. {e['numero']}. "
                 "No tiene validez legal. Empresa Demostracion S.A. de C.V.")
        pdf.multi_cell(0, 7, texto)
        archivo = f"{e['numero']}_contrato_demo.pdf"
        pdf.output(os.path.join(db.DOCS, archivo))
        dias = vencimientos.get(e["numero"])
        vence = (hoy + timedelta(days=dias)).isoformat() if dias is not None else ""
        con.execute("""INSERT INTO documentos (empleado_id, tipo, nombre, archivo, tamano, inicio, vence, notas)
                       VALUES (?, 'contrato', ?, ?, ?, ?, ?, ?)""",
                    (e["id"], f"Contrato {e['nombre'].title()}.pdf", archivo,
                     os.path.getsize(os.path.join(db.DOCS, archivo)), e["fecha_ingreso"], vence,
                     "Por tiempo determinado" if vence else "Por tiempo indefinido"))

for msg in ("Importó la información del reloj", "Creó el horario \"Oficina\" (tolerancia 10 min, comida 60 min)",
            "Agregó checada a mano a 106 JUAN PABLO RAMOS ORTIZ — Olvidó checar la salida"):
    db.log(msg, usuario="rh")
print(f"Base de demostración creada en {destino}: {len(emps)} empleados, {len(checadas)} checadas.")
print("Entrar con  usuario: demo   contraseña: demo123")
