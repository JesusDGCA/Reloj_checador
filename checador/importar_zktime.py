"""Importa empleados, departamentos, checadas y huellas desde la base de datos
del software de Steren / ZKTime.Net (archivo .db de respaldo).

Se puede correr varias veces: lo que ya existe no se duplica.
Uso por consola:  python importar_zktime.py ruta\\al\\respaldo.db
"""
import base64
import os
import sqlite3
import sys

import db


def importar(ruta):
    src = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    tablas = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "hr_employee" not in tablas:
        raise ValueError("Ese archivo no parece un respaldo del software Steren/ZKTime (no tiene hr_employee).")

    res = {"horarios": 0, "departamentos": 0, "empleados": 0, "fotos": 0, "checadas": 0, "huellas": 0}
    with db.db() as con:
        # empresa
        if "hr_company" in tablas:
            emp = src.execute("SELECT cmp_name FROM hr_company LIMIT 1").fetchone()
            if emp and emp["cmp_name"] and db.cfg("empresa") in ("", "Mi empresa"):
                con.execute("INSERT OR REPLACE INTO config VALUES ('empresa', ?)", (emp["cmp_name"],))
        if "att_terminal" in tablas:
            t = src.execute("SELECT terminal_tcpip, terminal_port FROM att_terminal LIMIT 1").fetchone()
            if t and t["terminal_tcpip"] and not db.cfg("ultima_sync_ok"):
                con.execute("INSERT OR REPLACE INTO config VALUES ('reloj_ip', ?)", (t["terminal_tcpip"],))
                con.execute("INSERT OR REPLACE INTO config VALUES ('reloj_puerto', ?)", (str(t["terminal_port"] or 4370),))

        # departamentos
        mapa_dep = {}
        for d in src.execute("SELECT id, dept_name FROM hr_department"):
            nombre = (d["dept_name"] or "").strip().upper() or "GENERAL"
            if nombre == "DEPARTMENT":
                nombre = "GENERAL"
            cur = con.execute("INSERT OR IGNORE INTO departamentos (nombre, horario_id) "
                              "VALUES (?, (SELECT MIN(id) FROM horarios))", (nombre,))
            res["departamentos"] += cur.rowcount
            mapa_dep[d["id"]] = con.execute("SELECT id FROM departamentos WHERE nombre=?", (nombre,)).fetchone()[0]

        # horarios (turnos de ZKTime) y a qué departamento se asignan
        mapa_turno = _importar_turnos(src, con, tablas, res)
        if mapa_turno and "att_department_shift" in tablas:
            for ds in src.execute("SELECT department_id, shift_id FROM att_department_shift ORDER BY startDate"):
                if ds["shift_id"] in mapa_turno and ds["department_id"] in mapa_dep:
                    con.execute("UPDATE departamentos SET horario_id=? WHERE id=?",
                                (mapa_turno[ds["shift_id"]], mapa_dep[ds["department_id"]]))
        if mapa_turno:  # el horario de ejemplo ya no hace falta si nadie lo usa
            con.execute("""DELETE FROM horarios WHERE nombre='General' AND id NOT IN (SELECT ? UNION SELECT ?)
                           AND id NOT IN (SELECT horario_id FROM departamentos WHERE horario_id IS NOT NULL)
                           AND id NOT IN (SELECT horario_id FROM empleados WHERE horario_id IS NOT NULL)""",
                        (min(mapa_turno.values()), max(mapa_turno.values())))

        # empleados
        mapa_emp = {}
        for e in src.execute("SELECT * FROM hr_employee"):
            numero = str(e["emp_pin"]).strip()
            mapa_emp[e["id"]] = numero
            fecha = lambda v: (v or "")[:10]
            cur = con.execute("""INSERT OR IGNORE INTO empleados
                (numero, nombre, apellidos, departamento_id, puesto, telefono, email, nss, direccion,
                 fecha_nacimiento, fecha_ingreso, fecha_baja, contacto_emergencia, tel_emergencia, activo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                numero, (e["emp_firstname"] or "").strip(), (e["emp_lastname"] or "").strip(),
                mapa_dep.get(e["department_id"]), e["emp_title"] or "", e["emp_phone"] or "",
                e["emp_email"] or "", e["emp_ssn"] or "", e["emp_address"] or "",
                fecha(e["emp_birthday"]), fecha(e["emp_hiredate"]), fecha(e["emp_firedate"]),
                e["emp_emergencyname"] or "", e["emp_emergencyphone1"] or "",
                1 if str(e["emp_active"]) == "1" else 0))
            res["empleados"] += cur.rowcount
            foto = e["emp_photo"]
            if cur.rowcount and foto and len(foto) > 100:
                nombre = f"{numero}_importada.jpg"
                with open(os.path.join(db.FOTOS, nombre), "wb") as f:
                    f.write(foto)
                con.execute("UPDATE empleados SET foto=? WHERE numero=?", (nombre, numero))
                res["fotos"] += 1

        # checadas
        if "att_punches" in tablas:
            for p in src.execute("SELECT employee_id, punch_time FROM att_punches"):
                numero = mapa_emp.get(p["employee_id"])
                if numero and p["punch_time"]:
                    cur = con.execute("INSERT OR IGNORE INTO checadas (numero, fecha_hora, origen) VALUES (?,?, 'importado')",
                                      (numero, p["punch_time"][:19]))
                    res["checadas"] += cur.rowcount

        # huellas
        if "hr_biotemplate" in tablas:
            for h in src.execute("SELECT employee_id, template_no, template_data FROM hr_biotemplate "
                                 "WHERE bio_type = 1 AND valid_flag = 1"):
                numero = mapa_emp.get(h["employee_id"])
                if not numero or not h["template_data"]:
                    continue
                try:
                    datos = base64.b64decode(h["template_data"])
                except Exception:
                    continue
                cur = con.execute("INSERT OR IGNORE INTO huellas (numero, dedo, plantilla) VALUES (?,?,?)",
                                  (numero, int(h["template_no"] or 0), datos))
                res["huellas"] += cur.rowcount
    src.close()
    db.log("Importado desde respaldo Steren: " + ", ".join(f"{v} {k}" for k, v in res.items()))
    return res


def _importar_turnos(src, con, tablas, res):
    """Convierte cada 'turno' de ZKTime en un horario semanal: qué pasa cada día de la semana."""
    import json
    from datetime import datetime
    if not {"att_shift", "att_shift_details", "att_timetable"} <= tablas:
        return {}
    flex = {}
    if "att_flexibleTimetable" in tablas:
        flex = {f["timetable_id"]: f for f in src.execute("SELECT * FROM att_flexibleTimetable")}
    comidas = {}
    if {"att_break", "att_break_timetable"} <= tablas:
        for b in src.execute("""SELECT bt.timetable_id, b.break_deductminute FROM att_break_timetable bt
                                JOIN att_break b ON b.id = bt.break_id"""):
            comidas[b["timetable_id"]] = b["break_deductminute"] or 0
    tablas_h = {t["id"]: t for t in src.execute("SELECT * FROM att_timetable")}

    mapa = {}
    for turno in src.execute("SELECT * FROM att_shift"):
        dias, usados = {str(i): None for i in range(7)}, []
        vistos = set()
        for det in src.execute("SELECT shift_date, timetable_id FROM att_shift_details WHERE shift_id=? "
                               "ORDER BY shift_date", (turno["id"],)):
            wd = datetime.strptime(det["shift_date"][:10], "%Y-%m-%d").weekday()
            if wd in vistos:
                continue
            vistos.add(wd)
            t = tablas_h.get(det["timetable_id"])
            if not t:
                continue
            usados.append(t)
            if str(t["timetableType"]) == "1":  # flexible
                f = flex.get(t["id"])
                dias[str(wd)] = {"tipo": "flexible", "minutos": int(f["requireWork"]) if f else 480}
            else:
                dias[str(wd)] = {"tipo": "fijo", "entrada": t["timetable_start"][11:16],
                                 "salida": t["timetable_end"][11:16]}
        if not usados:
            continue
        base = usados[0]
        nombre = turno["shift_name"] or "Horario"
        if nombre.lower() == "default":
            nombre = base["timetable_name"] or "Semanal"
        f0 = flex.get(base["id"])
        datos = (json.dumps(dias), int(base["timetable_latecome"] or 0) if str(base["timetableType"]) != "1" else 0,
                 comidas.get(base["id"], 0), int(f0["firstInLastOut"] if f0 else base["firstInLastOut"] or 0),
                 int(f0["enableOT"] if f0 else base["enableOT"] or 0))
        existente = con.execute("SELECT id FROM horarios WHERE nombre=?", (nombre,)).fetchone()
        if existente:
            mapa[turno["id"]] = existente[0]
        else:
            cur = con.execute("INSERT INTO horarios (nombre, dias, tolerancia, comida, primera_ultima, tiempo_extra) "
                              "VALUES (?,?,?,?,?,?)", (nombre,) + datos)
            mapa[turno["id"]] = cur.lastrowid
            res["horarios"] = res.get("horarios", 0) + 1
    return mapa


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    db.iniciar()
    print(importar(sys.argv[1]))
