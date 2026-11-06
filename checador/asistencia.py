"""Cálculo de asistencia: retardos, faltas, horas trabajadas, horas extra y faltantes.

Cada horario define, para cada día de la semana, una de tres cosas:
  - Descanso
  - Fijo:      hora de entrada y salida (cuenta retardos y salidas antes de tiempo)
  - Flexible:  horas a cubrir ese día; si tiene hora de entrada, también cuenta retardos

Reglas:
- Primera checada del día = entrada, última = salida.
- Normalmente se suman los tramos (entrada→sale a comer, regresa→salida).
  Con la opción "solo primera y última" se toma de la primera a la última checada.
- Flexible con hora de entrada: si la primera checada pasa de la entrada + tolerancia es retardo, aunque
  después complete sus horas. Se marca al tener las 4 checadas del día (o cuando el día ya pasó).
- En horario fijo, si solo hay 2 checadas se descuenta la comida (si el día fue de más de 5 h).
- Falta: día laboral sin ninguna checada (no cuenta antes de su ingreso ni después de su baja).
- Día festivo: no se espera que trabaje; si checa, todo lo trabajado cuenta como extra (si el horario lo permite).
- Día justificado (vacaciones, incapacidad, permiso…): no cuenta falta, retardo, salida antes ni horas faltantes.
- Dos checadas con menos de 2 minutos de diferencia cuentan como una (doble toque).
"""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta

import db

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _hm(texto):
    h, m = texto.split(":")[:2]
    return int(h) * 60 + int(m)


def _minutos(dt):
    return dt.hour * 60 + dt.minute


def fmt_horas(minutos):
    minutos = int(round(minutos or 0))
    return f"{minutos // 60}:{minutos % 60:02d}"


def normalizar(dia):
    """Convierte lo guardado para un día en un dict uniforme (o None si es descanso)."""
    if not dia:
        return None
    if isinstance(dia, list):  # formato viejo ["08:00","18:00"]
        return {"tipo": "fijo", "entrada": dia[0], "salida": dia[1]}
    if dia.get("tipo") == "flexible":
        plan = {"tipo": "flexible", "minutos": int(dia.get("minutos") or 0)}
        if dia.get("entrada"):
            plan["entrada"] = dia["entrada"]
        return plan
    if dia.get("tipo") == "fijo" and dia.get("entrada") and dia.get("salida"):
        return {"tipo": "fijo", "entrada": dia["entrada"], "salida": dia["salida"]}
    return None


def etiqueta_plan(plan):
    if not plan:
        return "Descanso"
    if plan["tipo"] == "flexible":
        m = plan["minutos"]
        texto = f"{m // 60} h{f' {m % 60} min' if m % 60 else ''} flexibles"
        return texto + (f" desde {plan['entrada']}" if plan.get("entrada") else "")
    return f"{plan['entrada']} – {plan['salida']}"


def requerido(plan, horario):
    """Minutos que se espera que trabaje ese día."""
    if not plan:
        return 0
    if plan["tipo"] == "flexible":
        return plan["minutos"]
    tramo = _hm(plan["salida"]) - _hm(plan["entrada"])
    if tramo < 0:
        tramo += 24 * 60
    return tramo - ((horario or {}).get("comida", 0) if tramo > 300 else 0)


def preparar_horario(h):
    h = dict(h)
    crudo = json.loads(h["dias"]) if isinstance(h["dias"], str) else h["dias"]
    h["dias"] = {str(i): normalizar(crudo.get(str(i))) for i in range(7)}
    h["resumen"] = resumen_horario(h)
    return h


def resumen_horario(h):
    """Texto corto: 'Lun–Vie 10 h flexibles · Sáb 6 h flexibles'."""
    grupos = []
    for i in range(7):
        et = etiqueta_plan(h["dias"][str(i)])
        if grupos and grupos[-1][1] == et:
            grupos[-1][0].append(i)
        else:
            grupos.append(([i], et))
    partes = []
    for dias, et in grupos:
        if et == "Descanso":
            continue
        nombre = DIAS_CORTOS[dias[0]] + (f"–{DIAS_CORTOS[dias[-1]]}" if len(dias) > 1 else "")
        partes.append(f"{nombre} {et}")
    return " · ".join(partes) or "Sin días laborales"


def horarios():
    with db.db() as con:
        return {h["id"]: preparar_horario(h) for h in con.execute("SELECT * FROM horarios")}


def empleados_con_horario(con, departamento_id=None, solo_activos=True, numero=None):
    sql = """SELECT e.*, d.nombre AS departamento,
                    COALESCE(e.horario_id, d.horario_id, (SELECT MIN(id) FROM horarios)) AS horario_ef
             FROM empleados e LEFT JOIN departamentos d ON d.id = e.departamento_id WHERE 1=1"""
    args = []
    if solo_activos:
        sql += " AND e.activo = 1"
    if departamento_id:
        sql += " AND e.departamento_id = ?"
        args.append(departamento_id)
    if numero:
        sql += " AND e.numero = ?"
        args.append(numero)
    sql += " ORDER BY CAST(e.numero AS INTEGER), e.numero"
    return [dict(r) for r in con.execute(sql, args)]


def _limpiar(checadas):
    out = []
    for c in sorted(checadas):
        if not out or (c - out[-1]).total_seconds() >= 120:
            out.append(c)
    return out


def calcular_dia(fecha, checadas, horario, emp, festivo=None, justificacion=None):
    """Resultado de un empleado en un día.
    festivo: nombre del día festivo (o None). justificacion: dict de la tabla justificaciones (o None)."""
    r = _calcular_dia(fecha, checadas, horario, emp, festivo)
    r["festivo"] = festivo or ""
    r["justificacion"] = justificacion
    if justificacion and r["plan"] and not festivo:
        # Justificado: se perdona la falta, el retardo, la salida antes y las horas que faltaron
        r["retardo"], r["faltante"], r["salio_antes"] = 0, 0, False
        if not checadas:
            if r["estado"] in ("falta", "pendiente"):
                r["estado"] = "justificado"
                r["requerido"] = 0
        elif r["estado"] == "retardo":
            r["estado"] = "asistencia"
        elif r["estado"] == "incompleto":
            r["estado"] = "asistencia"
    return r


def _calcular_dia(fecha, checadas, horario, emp, festivo=None):
    horario = horario or {"dias": {}, "tolerancia": 0, "comida": 0, "primera_ultima": 0, "tiempo_extra": 0}
    plan = horario["dias"].get(str(fecha.weekday()))
    hoy = date.today()
    tol = horario.get("tolerancia") or 0
    r = {"fecha": fecha, "dia": DIAS_CORTOS[fecha.weekday()], "checadas": checadas,
         "plan": plan, "plan_texto": etiqueta_plan(plan), "estado": "", "retardo": 0,
         "minutos": 0, "requerido": requerido(plan, horario), "extra": 0, "faltante": 0,
         "salio_antes": False, "texto": " · ".join(c.strftime("%H:%M") for c in checadas)}
    ingreso = (emp.get("fecha_ingreso") or "")[:10]
    baja = (emp.get("fecha_baja") or "")[:10]
    fuera = (ingreso and fecha.isoformat() < ingreso) or (baja and fecha.isoformat() > baja)
    es_festivo = bool(festivo and plan)
    if es_festivo:
        # día festivo: no se espera trabajo. Si checa, se calcula sin retardos y lo trabajado es extra
        r["plan_texto"] = f"Festivo: {festivo}"
        r["requerido"] = 0
        plan = r["plan"] = None

    if not checadas:
        if fuera or fecha > hoy:
            r["estado"] = ""
            r["requerido"] = 0
        elif es_festivo:
            r["estado"] = "festivo"
        elif not plan:
            r["estado"] = "descanso"
        elif fecha < hoy:
            r["estado"] = "falta"
            r["faltante"] = r["requerido"]
        elif plan["tipo"] == "fijo" and _minutos(datetime.now()) > _hm(plan["entrada"]) + tol:
            r["estado"] = "falta"
        else:
            r["estado"] = "pendiente"
        return r

    # fijo: el retardo se sabe al checar la entrada; flexible con hora de entrada: al cerrar el día (4 checadas)
    if plan and plan.get("entrada") and (plan["tipo"] == "fijo" or len(checadas) >= 4 or fecha < hoy):
        tarde = _minutos(checadas[0]) - (_hm(plan["entrada"]) + tol)
        if tarde > 0:
            r["retardo"] = tarde + tol
    if len(checadas) == 1:
        r["estado"] = "en turno" if fecha == hoy else "incompleto"
        return r

    lapso = (checadas[-1] - checadas[0]).total_seconds() / 60
    comida = horario.get("comida", 0) if plan and plan["tipo"] == "fijo" else 0
    if horario.get("primera_ultima"):
        r["minutos"] = lapso - (comida if lapso > 300 else 0)
    elif len(checadas) == 2:
        r["minutos"] = lapso - (comida if lapso > 300 else 0)
    else:  # se suman los tramos 1→2, 3→4, ...
        r["minutos"] = sum((checadas[i + 1] - checadas[i]).total_seconds() / 60
                           for i in range(0, len(checadas) - 1, 2))
        if len(checadas) % 2:
            r["estado"] = "en turno" if fecha == hoy else "incompleto"

    if plan and plan["tipo"] == "fijo" and fecha < hoy and \
            _minutos(checadas[-1]) < _hm(plan["salida"]) - tol:
        r["salio_antes"] = True
    cerrado = fecha < hoy and r["estado"] != "incompleto"
    if cerrado or (fecha == hoy and r["estado"] != "en turno"):
        diferencia = r["minutos"] - r["requerido"]
        if diferencia < -max(tol, 5) and cerrado:
            r["faltante"] = -diferencia
        if diferencia > 0 and horario.get("tiempo_extra"):
            r["extra"] = diferencia
    r["estado"] = r["estado"] or ("retardo" if r["retardo"] else "asistencia")
    return r


def reporte(desde, hasta, departamento_id=None, numero=None, solo_activos=True):
    """Resumen por empleado en un rango de fechas, con detalle por día."""
    hs = horarios()
    with db.db() as con:
        emps = empleados_con_horario(con, departamento_id, solo_activos, numero)
        filas = con.execute("SELECT numero, fecha_hora FROM checadas WHERE fecha_hora >= ? AND fecha_hora < ?",
                            (desde.isoformat(), (hasta + timedelta(days=1)).isoformat())).fetchall()
        fest = festivos(con, desde, hasta)
        justif = justificaciones(con, desde, hasta)
    por_emp_dia = defaultdict(list)
    for f in filas:
        dt = datetime.strptime(f["fecha_hora"], "%Y-%m-%d %H:%M:%S")
        por_emp_dia[(f["numero"], dt.date())].append(dt)

    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    resultado = []
    for e in emps:
        h = hs.get(e["horario_ef"])
        js = justif.get(e["id"], [])
        detalle = [calcular_dia(d, _limpiar(por_emp_dia.get((e["numero"], d), [])), h, e,
                                fest.get(d), _justificacion_del_dia(js, d)) for d in dias]
        resultado.append(resumir(e, h, detalle))
    return dias, resultado


def festivos(con, desde, hasta):
    """{fecha: nombre} de los días festivos en el rango."""
    return {datetime.strptime(f["fecha"], "%Y-%m-%d").date(): f["nombre"] for f in con.execute(
        "SELECT fecha, nombre FROM festivos WHERE fecha BETWEEN ? AND ?", (desde.isoformat(), hasta.isoformat()))}


def justificaciones(con, desde, hasta):
    """{empleado_id: [justificación, ...]} de las que tocan el rango."""
    out = defaultdict(list)
    for j in con.execute("SELECT * FROM justificaciones WHERE desde <= ? AND hasta >= ? ORDER BY desde",
                         (hasta.isoformat(), desde.isoformat())):
        j = dict(j)
        j["texto"] = db.TIPOS_JUSTIFICACION.get(j["tipo"], j["tipo"])
        j["abrev"] = db.ABREV_JUSTIFICACION.get(j["tipo"], "Justif.")
        out[j["empleado_id"]].append(j)
    return out


def _justificacion_del_dia(lista, dia):
    iso = dia.isoformat()
    return next((j for j in lista if j["desde"] <= iso <= j["hasta"]), None)


def resumir(e, h, detalle):
    return {
        "emp": e, "horario": h, "detalle": detalle,
        "asistencias": sum(1 for x in detalle if x["checadas"]),
        "laborables": sum(1 for x in detalle if x["plan"] and x["estado"] not in ("", "pendiente")),
        "faltas": sum(1 for x in detalle if x["estado"] == "falta"),
        "justificados": sum(1 for x in detalle if x["estado"] == "justificado"),
        "festivos": sum(1 for x in detalle if x["estado"] == "festivo"),
        "retardos": sum(1 for x in detalle if x["retardo"]),
        "min_retardo": sum(x["retardo"] for x in detalle),
        "incompletos": sum(1 for x in detalle if x["estado"] == "incompleto"),
        "minutos": sum(x["minutos"] for x in detalle),
        "requerido": sum(x["requerido"] for x in detalle if x["estado"] not in ("pendiente", "en turno")),
        "extra": sum(x["extra"] for x in detalle),
        "faltante": sum(x["faltante"] for x in detalle),
    }


def hoy():
    """Resumen rápido para la pantalla de inicio."""
    d = date.today()
    _, res = reporte(d, d)
    presentes = [r for r in res if r["detalle"][0]["checadas"]]
    faltan = [r for r in res if r["detalle"][0]["estado"] in ("falta", "pendiente")]
    retardos = [r for r in res if r["detalle"][0]["retardo"]]
    justificados = [r for r in res if r["detalle"][0]["estado"] == "justificado"]
    with db.db() as con:
        festivo = festivos(con, d, d).get(d, "")
    return {"presentes": presentes, "faltan": faltan, "retardos": retardos, "justificados": justificados,
            "festivo": festivo, "total": len(res)}
