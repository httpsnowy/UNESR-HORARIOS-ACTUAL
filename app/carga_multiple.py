"""Carga académica individual y múltiple con validación de conflictos, horas y bloqueos activos."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from . import db, queries, scheduler

DIAS_FORM = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
MINUTOS_HORA = 45


def _a_minutos(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _solapan(a: Tuple[str, str], b: Tuple[str, str]) -> bool:
    return max(_a_minutos(a[0]), _a_minutos(b[0])) < min(_a_minutos(a[1]), _a_minutos(b[1]))


def _hora_valida(valor: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(valor or "")))


def _entero(valor, default: int = 0) -> int:
    try:
        return db.normalizar_entero(valor, default=default)
    except ValueError:
        return int(default)


def _orden_dia(dia: str) -> int:
    dn = db.normalizar(dia)
    for i, nombre in enumerate(db.DIAS_ORDEN):
        if db.normalizar(nombre) == dn:
            return i
    return len(db.DIAS_ORDEN)


def _canon_dia(dia: str) -> str:
    dn = db.normalizar(dia)
    for nombre in db.DIAS_ORDEN:
        if db.normalizar(nombre) == dn:
            return nombre
    return str(dia or "").strip()


def minutos_slots(slots: List[Tuple[str, str, str]]) -> int:
    total = 0
    for _dia, ini, fin in slots or []:
        diff = _a_minutos(fin) - _a_minutos(ini)
        if diff > 0:
            total += diff
    return total


def horas_academicas_bloque(minutos: int) -> int:
    if minutos <= 0:
        return 0
    if minutos <= 60:
        return 1
    return max(1, int(minutos / float(MINUTOS_HORA) + 0.5))


def horas_slots(slots: List[Tuple[str, str, str]]) -> int:
    total = 0
    for _dia, ini, fin in slots or []:
        diff = _a_minutos(fin) - _a_minutos(ini)
        if diff > 0:
            total += horas_academicas_bloque(diff)
    return total


def formatear_horas(minutos: int) -> str:
    return str(horas_academicas_bloque(minutos))


def parsear_horas_materia_editada(valor: Any) -> Optional[int]:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    m = re.match(r"^(\d+)", texto)
    if not m:
        return None
    num = int(m.group(1))
    if num < 0 or num > 40:
        raise ValueError("Las horas de la materia deben estar entre 0 y 40.")
    return num


def validar_carrera_catalogo(carrera_nombre: str, prefijo_error: str = "") -> Optional[str]:
    limpio = " ".join(str(carrera_nombre or "").strip().split())
    p = f"{prefijo_error}: " if prefijo_error else ""
    if not limpio:
        return f"{p}la carrera es obligatoria."
    existentes = db.query("SELECT id FROM carreras LIMIT 1")
    if not existentes:
        return None
    if db.buscar_carrera_existente(limpio) is not None:
        return None
    canon = db.nombre_carrera_canonico(limpio)
    if canon in db.CARRERAS_CANONICAS:
        return None
    return (
        f"{p}la carrera «{limpio}» no está registrada en el sistema. "
        f"Seleccione una carrera de la lista desplegable para evitar duplicados."
    )


def validar_limite_horas(
    carrera: str,
    materia: str,
    slots: List[Tuple[str, str, str]],
    creditos: int = 0,
    horas_materia_form: Any = None,
    prefijo_error: str = "",
) -> Optional[str]:
    if not slots or not materia:
        return None
    p = f"{prefijo_error}: " if prefijo_error else ""
    try:
        editadas = parsear_horas_materia_editada(horas_materia_form)
    except ValueError as exc:
        return f"{p}{exc}"

    if editadas is not None:
        max_h = editadas
    else:
        max_h = queries.max_horas_materia(carrera, materia, creditos_form=creditos)

    if max_h <= 0:
        return None
    total_h = horas_slots(slots)
    if total_h > max_h:
        return (
            f"{p}«{materia}» permite un máximo de {max_h} hora(s) semanal(es) "
            f"y seleccionó {total_h} hora(s). Desmarque bloques o ajuste el campo «Horas de la materia»."
        )
    return None


def validar_contra_bloqueos(
    profesor: str,
    ambiente: str,
    slots: List[Tuple[str, str, str]],
    prefijo_error: str = "",
    bloqueos: Optional[List[Dict]] = None,
) -> List[str]:
    """Comprueba que los bloques elegidos no choquen con bloqueos activos."""
    reglas = bloqueos if bloqueos is not None else queries.obtener_bloqueos(solo_activos=True)
    if not reglas or not slots:
        return []
    errores: List[str] = []
    p = f"{prefijo_error}: " if prefijo_error else ""
    amb_u = str(ambiente or "").strip().upper()
    vistos = set()
    for dia, ini, fin in slots:
        blq_d = scheduler.bloqueo_docente_en(profesor, dia, (ini, fin), reglas)
        if blq_d is not None:
            msg = f"{p}bloqueo activo el {dia} {ini}–{fin}: {queries.descripcion_bloqueo(blq_d)}."
            if msg not in vistos:
                vistos.add(msg)
                errores.append(msg)
        if amb_u:
            blq_s = scheduler.bloqueo_salon_en(amb_u, dia, (ini, fin), reglas)
            if blq_s is not None:
                msg = (
                    f"{p}el ambiente preferido {amb_u} está bloqueado el {dia} {ini}–{fin}: "
                    f"{queries.descripcion_bloqueo(blq_s)}."
                )
                if msg not in vistos:
                    vistos.add(msg)
                    errores.append(msg)
        else:
            # Si hay bloqueo global de "todos los ambientes" en esa franja
            for r in reglas:
                if r.get("tipo") == "todos" and scheduler._regla_aplica_en_tiempo(r, dia, (ini, fin)):
                    msg = f"{p}bloqueo activo el {dia} {ini}–{fin}: {queries.descripcion_bloqueo(r)}."
                    if msg not in vistos:
                        vistos.add(msg)
                        errores.append(msg)
                    break
    return errores


def extraer_bloques_formulario(form, indice_fila: Optional[int] = None) -> List[Dict]:
    bloques: List[Dict] = []
    if indice_fila is None:
        patron = re.compile(r"^bloque_(?:inicio|fin|dias)_(\d+)$")
        subindices = sorted({int(m.group(1)) for k in form.keys() for m in [patron.match(k)] if m})
        if subindices:
            for b in subindices:
                bloques.append({
                    "dias": [_canon_dia(d) for d in form.getlist(f"bloque_dias_{b}") if str(d).strip()],
                    "hora_inicio": str(form.get(f"bloque_inicio_{b}", "")).strip(),
                    "hora_fin": str(form.get(f"bloque_fin_{b}", "")).strip(),
                })
            return bloques
        return [{
            "dias": [_canon_dia(d) for d in form.getlist("dia") if str(d).strip()],
            "hora_inicio": str(form.get("hora_inicio", "")).strip(),
            "hora_fin": str(form.get("hora_fin", "")).strip(),
        }]

    patron = re.compile(rf"^bloque_(?:inicio|fin|dias)_{indice_fila}_(\d+)$")
    subindices = sorted({int(m.group(1)) for k in form.keys() for m in [patron.match(k)] if m})
    if subindices:
        for b in subindices:
            bloques.append({
                "dias": [_canon_dia(d) for d in form.getlist(f"bloque_dias_{indice_fila}_{b}") if str(d).strip()],
                "hora_inicio": str(form.get(f"bloque_inicio_{indice_fila}_{b}", "")).strip(),
                "hora_fin": str(form.get(f"bloque_fin_{indice_fila}_{b}", "")).strip(),
            })
        return bloques
    return [{
        "dias": [_canon_dia(d) for d in form.getlist(f"dia_{indice_fila}") if str(d).strip()],
        "hora_inicio": str(form.get(f"hora_inicio_{indice_fila}", "")).strip(),
        "hora_fin": str(form.get(f"hora_fin_{indice_fila}", "")).strip(),
    }]


def expandir_slots(horarios: List[Dict], prefijo_error: str = "") -> Tuple[List[Tuple[str, str, str]], List[str]]:
    errores: List[str] = []
    slots: List[Tuple[str, str, str]] = []
    vistos = set()
    p = f"{prefijo_error}: " if prefijo_error else ""

    bloques_con_dias = [b for b in (horarios or []) if b.get("dias")]
    if not bloques_con_dias:
        if horarios:
            ini = str(horarios[0].get("hora_inicio", "")).strip()
            fin = str(horarios[0].get("hora_fin", "")).strip()
            if (ini or fin) and (not _hora_valida(ini) or not _hora_valida(fin) or _a_minutos(ini) >= _a_minutos(fin)):
                errores.append(f"{p}el rango horario no es válido (la hora de inicio debe ser menor a la de fin).")
        errores.append(f"{p}seleccione al menos un día de clase.")
        return [], errores

    for idx, b in enumerate(bloques_con_dias, start=1):
        ini = str(b.get("hora_inicio", "")).strip()
        fin = str(b.get("hora_fin", "")).strip()
        etq = f"bloque horario {idx}: " if len(bloques_con_dias) > 1 else ""
        if not _hora_valida(ini) or not _hora_valida(fin):
            errores.append(f"{p}{etq}el rango horario no es válido.")
            continue
        if _a_minutos(ini) >= _a_minutos(fin):
            errores.append(f"{p}{etq}la hora de inicio debe ser menor a la de fin.")
            continue
        for dia in b["dias"]:
            d_canon = _canon_dia(dia)
            clave = (db.normalizar(d_canon), ini, fin)
            if clave not in vistos:
                vistos.add(clave)
                slots.append((d_canon, ini, fin))

    slots.sort(key=lambda s: (_orden_dia(s[0]), _a_minutos(s[1]), _a_minutos(s[2])))

    for i, a in enumerate(slots):
        for b in slots[i + 1:]:
            if db.normalizar(a[0]) == db.normalizar(b[0]) and _solapan((a[1], a[2]), (b[1], b[2])):
                errores.append(
                    f"{p}hay bloques horarios solapados el {a[0]} "
                    f"({a[1]}–{a[2]} y {b[1]}–{b[2]})."
                )
    return slots, errores


def buscar_o_crear_profesor(nombre: str, cedula: str = "", email: str = "", condicion: str = "") -> int:
    nombre_limpio = " ".join(str(nombre or "").strip().split())
    objetivo = db.normalizar(nombre_limpio)
    prof_id = None
    for p in db.query("SELECT id,nombre,cedula,email,condicion FROM profesores"):
        if db.normalizar(p["nombre"]) == objetivo:
            prof_id = int(p["id"])
            actual = p
            break
    if prof_id is None:
        prof_id = db.get_or_create("profesores", "nombre", nombre_limpio.upper())
        actual = {"cedula": "", "email": "", "condicion": ""}

    if cedula or email or condicion:
        db.execute(
            "UPDATE profesores SET cedula=?, email=?, condicion=? WHERE id=?",
            (
                cedula or actual.get("cedula", ""),
                email or actual.get("email", ""),
                condicion or actual.get("condicion", ""),
                prof_id,
            ),
        )
    return prof_id


def buscar_o_crear_carrera(nombre: str) -> int:
    cid = db.get_or_create_carrera_segura(nombre, permitir_crear=True)
    if cid is None:
        raise ValueError("La carrera es obligatoria.")
    return int(cid)


def buscar_o_crear_materia(nombre: str, car_id: int, codigo: str = "",
                           semestre: str = "1er Semestre", creditos: int = 0) -> int:
    return db.get_or_create_materia(nombre, car_id, codigo, semestre, creditos)


def guardar_carga_y_bloques(
    prof_id: int,
    mat_id: int,
    seccion: str,
    slots: List[Tuple[str, str, str]],
    bloques_solicitados: int = 1,
    ambiente: str = "",
    compartidos: bool = False,
) -> Tuple[int, int]:
    nuevas_disp = 0
    for dia, ini, fin in slots:
        existe = db.query(
            """SELECT id FROM disponibilidades WHERE profesor_id=? AND dia=?
               AND hora_inicio=? AND hora_fin=? LIMIT 1""",
            (prof_id, dia, ini, fin),
        )
        if not existe:
            db.execute(
                """INSERT INTO disponibilidades (profesor_id,dia,hora_inicio,hora_fin)
                   VALUES (?,?,?,?)""",
                (prof_id, dia, ini, fin),
            )
            nuevas_disp += 1

    bloques_final = len(slots) if slots else max(1, int(bloques_solicitados or 1))
    dia_fijo = "|".join(s[0] for s in slots)
    ini_fija = "|".join(s[1] for s in slots)
    fin_fija = "|".join(s[2] for s in slots)
    amb_limpio = str(ambiente or "").strip().upper()
    comp_txt = "COMPARTIDOS" if compartidos else ""
    sec_limpia = (seccion or "").strip() or "Sección A"

    existe_carga = db.query(
        """SELECT id FROM carga_academica WHERE profesor_id=? AND
           materia_id=? AND seccion=? LIMIT 1""",
        (prof_id, mat_id, sec_limpia),
    )
    if existe_carga:
        cid = int(existe_carga[0]["id"])
        db.execute(
            """UPDATE carga_academica
               SET bloques_semanales=?, salon_preferido=?, dia_fijo=?,
                   hora_inicio_fija=?, hora_fin_fija=?, compartidos=?
               WHERE id=?""",
            (bloques_final, amb_limpio, dia_fijo, ini_fija, fin_fija, comp_txt, cid),
        )
    else:
        cid = int(db.execute(
            """INSERT INTO carga_academica
               (profesor_id,materia_id,seccion,bloques_semanales,salon_preferido,
                dia_fijo,hora_inicio_fija,hora_fin_fija,compartidos)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (prof_id, mat_id, sec_limpia, bloques_final, amb_limpio,
             dia_fijo, ini_fija, fin_fija, comp_txt),
        ))
        if not cid:
            fila_c = db.query(
                """SELECT id FROM carga_academica WHERE profesor_id=? AND
                   materia_id=? AND seccion=? LIMIT 1""",
                (prof_id, mat_id, sec_limpia),
            )
            cid = int(fila_c[0]["id"]) if fila_c else 0
    return cid, nuevas_disp


def parsear_filas_json(lista_cruda: Any) -> List[Dict]:
    if isinstance(lista_cruda, str):
        lista_cruda = json.loads(lista_cruda)
    if not isinstance(lista_cruda, list):
        return []

    filas: List[Dict] = []
    num_visible = 0
    for idx_original, item in enumerate(lista_cruda):
        if not isinstance(item, dict):
            continue
        profesor = str(item.get("profesor") or "").strip()
        carrera = str(item.get("carrera") or "").strip()
        materia = str(item.get("materia") or "").strip()
        codigo = str(item.get("codigo") or "").strip()
        if not any((profesor, carrera, materia, codigo)):
            continue
        num_visible += 1
        horarios_raw = item.get("horarios") or []
        horarios: List[Dict] = []
        dias_planos: List[str] = []
        for h in horarios_raw:
            if not isinstance(h, dict):
                continue
            ds = [_canon_dia(d) for d in (h.get("dias") or []) if str(d).strip()]
            ini = str(h.get("hora_inicio") or "").strip()
            fin = str(h.get("hora_fin") or "").strip()
            horarios.append({"dias": ds, "hora_inicio": ini, "hora_fin": fin})
            for d in ds:
                if d not in dias_planos:
                    dias_planos.append(d)
        if not horarios and item.get("dias"):
            ds = [_canon_dia(d) for d in (item.get("dias") or []) if str(d).strip()]
            horarios = [{
                "dias": ds,
                "hora_inicio": str(item.get("hora_inicio") or "").strip(),
                "hora_fin": str(item.get("hora_fin") or "").strip(),
            }]
            dias_planos = list(ds)
        primero = horarios[0] if horarios else {"hora_inicio": "", "hora_fin": ""}
        filas.append({
            "indice": num_visible,
            "indice_ui": int(item.get("indice_ui", idx_original)),
            "profesor": profesor,
            "cedula": str(item.get("cedula") or "").strip(),
            "email": str(item.get("email") or "").strip(),
            "condicion": str(item.get("condicion") or "").strip(),
            "carrera": carrera,
            "materia": materia,
            "codigo": codigo,
            "seccion": str(item.get("seccion") or "").strip() or "Sección A",
            "semestre": str(item.get("semestre") or "").strip() or "1er Semestre",
            "creditos": "" if item.get("creditos") is None else str(item.get("creditos")).strip(),
            "horas_materia": "" if item.get("horas_materia") is None else str(item.get("horas_materia")).strip(),
            "bloques": "" if item.get("bloques") is None else str(item.get("bloques")).strip(),
            "ambiente": str(item.get("ambiente") or "").strip().upper(),
            "compartidos": bool(item.get("compartidos")),
            "horarios": horarios,
            "dias": dias_planos,
            "hora_inicio": primero["hora_inicio"],
            "hora_fin": primero["hora_fin"],
        })
    return filas


def parsear_filas(form) -> List[Dict]:
    raw_json = form.get("filas_json")
    if raw_json and str(raw_json).strip():
        try:
            return parsear_filas_json(str(raw_json))
        except Exception:
            pass

    patron = re.compile(
        r"^(?:profesor|carrera|materia|codigo|seccion|bloque_inicio|hora_inicio)_(\d+)(?:_\d+)?$"
    )
    indices = {int(m.group(1)) for k in form.keys() for m in [patron.match(k)] if m}
    total = min(max(_entero(form.get("total_filas"), 0), 0), 1000)
    indices.update(range(total))

    filas: List[Dict] = []
    num_visible = 0
    for i in sorted(indices):
        pref = f"_{i}"
        profesor = str(form.get("profesor" + pref, "")).strip()
        carrera = str(form.get("carrera" + pref, "")).strip()
        materia = str(form.get("materia" + pref, "")).strip()
        codigo = str(form.get("codigo" + pref, "")).strip()
        if not any((profesor, carrera, materia, codigo)):
            continue
        num_visible += 1
        horarios = extraer_bloques_formulario(form, indice_fila=i)
        dias_planos: List[str] = []
        for h in horarios:
            for d in h["dias"]:
                if d not in dias_planos:
                    dias_planos.append(d)
        primero = horarios[0] if horarios else {"hora_inicio": "", "hora_fin": ""}
        filas.append({
            "indice": num_visible,
            "indice_ui": i,
            "profesor": profesor,
            "cedula": str(form.get("cedula" + pref, "")).strip(),
            "email": str(form.get("email" + pref, "")).strip(),
            "condicion": str(form.get("condicion" + pref, "")).strip(),
            "carrera": carrera,
            "materia": materia,
            "codigo": codigo,
            "seccion": str(form.get("seccion" + pref, "")).strip() or "Sección A",
            "semestre": str(form.get("semestre" + pref, "")).strip() or "1er Semestre",
            "creditos": form.get("creditos" + pref, ""),
            "horas_materia": str(form.get("horas_materia" + pref, "")).strip(),
            "bloques": form.get("bloques" + pref, ""),
            "ambiente": str(form.get("ambiente" + pref, "")).strip().upper(),
            "compartidos": bool(form.get("compartidos" + pref)),
            "horarios": horarios,
            "dias": dias_planos,
            "hora_inicio": primero["hora_inicio"],
            "hora_fin": primero["hora_fin"],
        })
    return filas


def validar_filas_detallado(filas: List[Dict]) -> Tuple[List[str], Dict[int, List[str]]]:
    errores: List[str] = []
    por_fila: Dict[int, List[str]] = {}

    def _add(indice_fila: int, mensaje: str) -> None:
        errores.append(mensaje)
        por_fila.setdefault(indice_fila, []).append(mensaje)

    if not filas:
        return ["Agregue al menos una materia a la carga."], {}

    bloqueos_activos = queries.obtener_bloqueos(solo_activos=True)

    for f in filas:
        n = f["indice"]
        try:
            f["cedula"] = db.normalizar_cedula(f.get("cedula", ""))
        except ValueError as exc:
            _add(n, f"Materia {n}: {exc}")
        for campo, opciones in (
            ("creditos", {"minimo": 0, "maximo": 30, "default": 0}),
            ("bloques", {"minimo": 1, "maximo": 40, "default": 1}),
        ):
            try:
                f[campo] = db.normalizar_entero(f.get(campo), **opciones)
            except ValueError as exc:
                _add(n, f"Materia {n}: {campo} — {exc}")
        if not f["profesor"]:
            _add(n, f"Materia {n}: el docente es obligatorio.")
        err_car = validar_carrera_catalogo(f["carrera"], prefijo_error=f"Materia {n}")
        if err_car:
            _add(n, err_car)
        if not f["materia"]:
            _add(n, f"Materia {n}: la materia es obligatoria.")

        horarios = f.get("horarios") or [{
            "dias": f.get("dias", []),
            "hora_inicio": f.get("hora_inicio", ""),
            "hora_fin": f.get("hora_fin", ""),
        }]
        slots, errs_h = expandir_slots(horarios, prefijo_error=f"Materia {n}")
        f["slots"] = slots
        for eh in errs_h:
            _add(n, eh)
        if slots:
            f["bloques"] = len(slots)
            if f["materia"]:
                err_lim = validar_limite_horas(
                    f["carrera"],
                    f["materia"],
                    slots,
                    creditos=f["creditos"] if isinstance(f.get("creditos"), int) else 0,
                    horas_materia_form=f.get("horas_materia"),
                    prefijo_error=f"Materia {n}",
                )
                if err_lim:
                    _add(n, err_lim)
            for err_blq in validar_contra_bloqueos(
                f["profesor"], f["ambiente"], slots,
                prefijo_error=f"Materia {n}", bloqueos=bloqueos_activos
            ):
                _add(n, err_blq)

    vistos: Dict[Tuple[str, str, str], int] = {}
    for f in filas:
        clave = (db.normalizar(f["profesor"]), db.normalizar(f["materia"]), db.normalizar(f["seccion"]))
        if clave in vistos:
            _add(f["indice"], f"Materia {f['indice']}: la misma materia y sección ya está en la Materia {vistos[clave]}.")
        else:
            vistos[clave] = f["indice"]

    for i, a in enumerate(filas):
        for b in filas[i + 1:]:
            choque_prof_reportado = False
            choque_amb_reportado = False
            for da, ia, fa in a.get("slots", []):
                for db_, ib, fb in b.get("slots", []):
                    if db.normalizar(da) != db.normalizar(db_):
                        continue
                    if not _solapan((ia, fa), (ib, fb)):
                        continue
                    if (not choque_prof_reportado
                            and db.normalizar(a["profesor"]) == db.normalizar(b["profesor"])
                            and not (a["compartidos"] and b["compartidos"])):
                        msg = (
                            f"Conflicto: {a['profesor']} tiene dos materias el {da} "
                            f"({ia}–{fa} y {ib}–{fb}) en Materia {a['indice']} y Materia {b['indice']}."
                        )
                        _add(b["indice"], msg)
                        choque_prof_reportado = True
                    if (not choque_amb_reportado
                            and a["ambiente"] and a["ambiente"] == b["ambiente"]
                            and not scheduler.es_compartible(a["ambiente"])):
                        msg = (
                            f"Conflicto: el ambiente {a['ambiente']} se repite el {da} "
                            f"({ia}–{fa} y {ib}–{fb}) en Materia {a['indice']} y Materia {b['indice']}."
                        )
                        _add(b["indice"], msg)
                        choque_amb_reportado = True

    manuales = db.query("SELECT * FROM asignaciones_horario WHERE estado='Manual'")
    profesores = {db.normalizar(p["nombre"]): int(p["id"]) for p in db.query("SELECT id,nombre FROM profesores")}
    salones = {str(s["codigo"]).upper(): int(s["id"]) for s in db.query("SELECT id,codigo FROM salones")}
    for f in filas:
        pid = profesores.get(db.normalizar(f["profesor"]))
        sid = salones.get(f["ambiente"])
        for dia, ini, fin in f.get("slots", []):
            for a in manuales:
                if db.normalizar(dia) != db.normalizar(a["dia"]):
                    continue
                if not _solapan((ini, fin), (a["hora_inicio"], a["hora_fin"])):
                    continue
                if pid is not None and int(a["profesor_id"]) == pid and not f["compartidos"]:
                    _add(
                        f["indice"],
                        f"Conflicto: {f['profesor']} ya tiene una clase manual el {dia} "
                        f"{a['hora_inicio']}–{a['hora_fin']} (Materia {f['indice']}).",
                    )
                if sid is not None and int(a["salon_id"]) == sid and not scheduler.es_compartible(f["ambiente"]):
                    _add(
                        f["indice"],
                        f"Conflicto: el ambiente {f['ambiente']} ya está ocupado manualmente el {dia} "
                        f"{a['hora_inicio']}–{a['hora_fin']} (Materia {f['indice']}).",
                    )
    return errores, por_fila


def validar_filas(filas: List[Dict]) -> List[str]:
    errores, _ = validar_filas_detallado(filas)
    return errores


def guardar_filas(filas: List[Dict]) -> Dict:
    respaldo = db.respaldar_bd("antes_carga_multiple")
    guardados = {"profesores": 0, "materias": 0, "disponibilidades": 0, "carga": 0}
    carga_ids: List[int] = []
    carreras_ids: List[int] = []

    try:
        for f in filas:
            cedula = db.normalizar_cedula(f.get("cedula", ""))
            prof_id = buscar_o_crear_profesor(
                f["profesor"],
                cedula=cedula,
                email=f.get("email", ""),
                condicion=f.get("condicion", ""),
            )
            guardados["profesores"] += 1

            car_id = buscar_o_crear_carrera(f["carrera"])
            carreras_ids.append(car_id)

            creditos = db.normalizar_entero(f.get("creditos"), minimo=0, maximo=30, default=0)
            mat_id = buscar_o_crear_materia(
                f["materia"], car_id, f.get("codigo", ""), f.get("semestre", "1er Semestre"), creditos
            )
            guardados["materias"] += 1

            slots = f.get("slots")
            if not slots:
                horarios = f.get("horarios") or [{
                    "dias": f.get("dias", []),
                    "hora_inicio": f.get("hora_inicio", ""),
                    "hora_fin": f.get("hora_fin", ""),
                }]
                slots, _ = expandir_slots(horarios)

            bloques = len(slots) if slots else 1
            cid, nuevas_disp = guardar_carga_y_bloques(
                prof_id=prof_id,
                mat_id=mat_id,
                seccion=f.get("seccion", "Sección A"),
                slots=slots,
                bloques_solicitados=bloques,
                ambiente=f.get("ambiente", ""),
                compartidos=bool(f.get("compartidos")),
            )
            guardados["disponibilidades"] += nuevas_disp
            guardados["carga"] += 1
            carga_ids.append(cid)

        resultado = scheduler.generar_horarios_automaticos()
    except Exception:
        db.restaurar_bd(respaldo)
        raise

    return {
        "guardados": guardados,
        "asignacion": resultado,
        "carga_ids": carga_ids,
        "carreras_ids": carreras_ids,
    }
