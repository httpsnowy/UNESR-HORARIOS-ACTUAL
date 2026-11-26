"""Generación automática de horarios, bloqueos de día/hora y edición/borrado granular."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from . import db, queries

DIAS = db.DIAS_ORDEN


def es_compartible(codigo: str) -> bool:
    c = db.normalizar(codigo)
    return any(k in c for k in ("VIRTUAL", "COORDINAC", "ONLINE", "AUDITORIO", "CANCHA", "SATELITAL"))


def _a_minutos(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _franjas_solapadas(a: Tuple[str, str], b: Tuple[str, str]) -> bool:
    return max(_a_minutos(a[0]), _a_minutos(b[0])) < min(_a_minutos(a[1]), _a_minutos(b[1]))


def _hora_mayor(a: str, b: str) -> str:
    return a if _a_minutos(a) >= _a_minutos(b) else b


def _hora_menor(a: str, b: str) -> str:
    return a if _a_minutos(a) <= _a_minutos(b) else b


def _dias_ordenados(dia: str) -> int:
    d = db.normalizar(dia)
    for i, nombre in enumerate(DIAS):
        if db.normalizar(nombre) == d:
            return i
    return len(DIAS)


def _canon_dia(dia: str) -> str:
    dn = db.normalizar(dia)
    for nombre in DIAS:
        if db.normalizar(nombre) == dn:
            return nombre
    return str(dia or "").strip()


def _parsear_bloques_fijos(dia_fijo: str, ini_fija: str, fin_fija: str) -> List[Tuple[str, str, str]]:
    if not (dia_fijo and ini_fija and fin_fija):
        return []
    dias = [x.strip() for x in str(dia_fijo).split("|") if x.strip()]
    inis = [x.strip() for x in str(ini_fija).split("|") if x.strip()]
    fins = [x.strip() for x in str(fin_fija).split("|") if x.strip()]
    if not dias or not inis or not fins:
        return []
    if len(inis) == 1 and len(fins) == 1 and len(dias) > 1:
        inis = inis * len(dias)
        fins = fins * len(dias)
    total = min(len(dias), len(inis), len(fins))
    bloques = [(_canon_dia(dias[i]), inis[i], fins[i]) for i in range(total)]
    bloques.sort(key=lambda x: (_dias_ordenados(x[0]), _a_minutos(x[1]), _a_minutos(x[2])))
    return bloques


def _regla_aplica_en_tiempo(regla: Dict, dia: str, franja: Tuple[str, str]) -> bool:
    if not regla.get("activo"):
        return False
    rdia = db.normalizar(regla.get("dia"))
    if rdia != "TODOS" and rdia != db.normalizar(dia):
        return False
    if regla.get("todo_el_dia"):
        return True
    return _franjas_solapadas(franja, (regla["hora_inicio"], regla["hora_fin"]))


def bloqueo_salon_en(codigo_salon: str, dia: str, franja: Tuple[str, str],
                     bloqueos: Optional[List[Dict]] = None) -> Optional[Dict]:
    """Devuelve la regla activa que bloquea ``codigo_salon`` en ``(dia, franja)``, o ``None``."""
    reglas = bloqueos if bloqueos is not None else queries.obtener_bloqueos(solo_activos=True)
    if not reglas:
        return None
    cod_u = str(codigo_salon or "").strip().upper()
    sector, _ = db.categoria_ambiente(cod_u)
    sec_n = db.normalizar(sector)
    for r in reglas:
        if not _regla_aplica_en_tiempo(r, dia, franja):
            continue
        tipo = r.get("tipo")
        if tipo == "todos":
            return r
        if tipo == "piso" and db.normalizar(r.get("objetivo")) == sec_n:
            return r
        if tipo == "ambiente" and str(r.get("objetivo") or "").strip().upper() == cod_u:
            return r
    return None


def bloqueo_docente_en(nombre_profesor: str, dia: str, franja: Tuple[str, str],
                       bloqueos: Optional[List[Dict]] = None) -> Optional[Dict]:
    """Devuelve la regla activa que bloquea al docente en ``(dia, franja)``, o ``None``."""
    reglas = bloqueos if bloqueos is not None else queries.obtener_bloqueos(solo_activos=True)
    if not reglas:
        return None
    prof_n = db.normalizar(nombre_profesor)
    for r in reglas:
        if r.get("tipo") != "docente":
            continue
        if not _regla_aplica_en_tiempo(r, dia, franja):
            continue
        if db.normalizar(r.get("objetivo")) == prof_n:
            return r
    return None


def _sincronizar_carga_desde_asignaciones(carga_id: int) -> int:
    cid = int(carga_id)
    restantes = db.query(
        "SELECT id, dia, hora_inicio, hora_fin, salon_id FROM asignaciones_horario WHERE carga_id=?",
        (cid,),
    )
    if not restantes:
        db.execute("DELETE FROM carga_academica WHERE id=?", (cid,))
        return 0

    restantes.sort(key=lambda r: (_dias_ordenados(r["dia"]), _a_minutos(r["hora_inicio"]), _a_minutos(r["hora_fin"])))
    dia_fijo = "|".join(_canon_dia(r["dia"]) for r in restantes)
    ini_fija = "|".join(str(r["hora_inicio"]).strip() for r in restantes)
    fin_fija = "|".join(str(r["hora_fin"]).strip() for r in restantes)
    db.execute(
        """UPDATE carga_academica
           SET bloques_semanales=?, dia_fijo=?, hora_inicio_fija=?, hora_fin_fija=?
           WHERE id=?""",
        (len(restantes), dia_fijo, ini_fija, fin_fija, cid),
    )
    return len(restantes)


def _salon_libre_en(
    salon: Dict,
    dia: str,
    franja: Tuple[str, str],
    salon_ocupado: Dict[int, List[Tuple[str, str, str]]],
    bloqueos: List[Dict],
) -> bool:
    if bloqueo_salon_en(salon["codigo"], dia, franja, bloqueos) is not None:
        return False
    if es_compartible(salon["codigo"]):
        return True
    sid = int(salon["id"])
    return not any(
        db.normalizar(d) == db.normalizar(dia) and _franjas_solapadas(franja, (o_ini, o_fin))
        for d, o_ini, o_fin in salon_ocupado[sid]
    )


def generar_horarios_automaticos() -> Dict:
    todos_salones = db.query("SELECT id,codigo,capacidad FROM salones ORDER BY id")
    if not todos_salones:
        return {"asignados": 0, "pendientes": 0, "mensajes": ["No hay ambientes registrados."], "detalles": []}

    oficiales = db.ambientes_oficiales(todos_salones)
    salones = oficiales if oficiales else todos_salones
    bloqueos_activos = queries.obtener_bloqueos(solo_activos=True)

    disponibilidad: Dict[int, List[Tuple[str, str, str]]] = defaultdict(list)
    for d in db.query("SELECT profesor_id,dia,hora_inicio,hora_fin FROM disponibilidades"):
        disponibilidad[int(d["profesor_id"])].append((d["dia"], d["hora_inicio"], d["hora_fin"]))

    carga = db.query("""
        SELECT ca.id, ca.profesor_id, ca.materia_id, ca.seccion, ca.bloques_semanales,
               ca.salon_preferido, ca.dia_fijo, ca.hora_inicio_fija, ca.hora_fin_fija,
               ca.compartidos, p.nombre AS profesor, m.nombre AS materia
        FROM carga_academica ca
        JOIN profesores p ON p.id=ca.profesor_id
        JOIN materias m ON m.id=ca.materia_id
        ORDER BY p.nombre, m.nombre, ca.seccion
    """)

    carga.sort(key=lambda c: (
        0 if (c.get("dia_fijo") and c.get("hora_inicio_fija") and c.get("hora_fin_fija")) else 1,
        str(c["profesor"] or ""),
        str(c["materia"] or ""),
        str(c["seccion"] or ""),
    ))

    materias_nombre = {int(m["id"]): m["nombre"] for m in db.query("SELECT id,nombre FROM materias")}

    prof_ocupado: Dict[int, List[Tuple[str, str, str, str]]] = defaultdict(list)
    salon_ocupado: Dict[int, List[Tuple[str, str, str]]] = defaultdict(list)
    uso_salon: Dict[int, int] = defaultdict(int)
    manuales_por_carga: Dict[int, int] = defaultdict(int)
    manuales_slots_por_carga: Dict[int, set] = defaultdict(set)
    manual_salon_por_carga: Dict[int, int] = {}

    for a in db.query("SELECT * FROM asignaciones_horario WHERE estado = 'Manual'"):
        mat_nom = materias_nombre.get(int(a["materia_id"]), "otra materia")
        prof_ocupado[int(a["profesor_id"])].append((a["dia"], a["hora_inicio"], a["hora_fin"], mat_nom))
        salon_ocupado[int(a["salon_id"])].append((a["dia"], a["hora_inicio"], a["hora_fin"]))
        uso_salon[int(a["salon_id"])] += 1
        cid_m = int(a["carga_id"])
        manuales_por_carga[cid_m] += 1
        manuales_slots_por_carga[cid_m].add((db.normalizar(a["dia"]), str(a["hora_inicio"]).strip(), str(a["hora_fin"]).strip()))
        manual_salon_por_carga.setdefault(cid_m, int(a["salon_id"]))

    db.borrar_donde_neq("asignaciones_horario", "estado", "Manual")

    asignados = sum(manuales_por_carga.values())
    pendientes = 0
    mensajes: List[str] = []
    detalles: List[Dict] = []
    codigo_id = {str(s["codigo"]).strip().upper(): int(s["id"]) for s in salones}

    for c in carga:
        cid, pid, mid = int(c["id"]), int(c["profesor_id"]), int(c["materia_id"])
        compartido = bool(str(c["compartidos"] or "").strip())
        pref = str(c["salon_preferido"] or "").strip().upper()
        pref_id = codigo_id.get(pref)

        fijos = _parsear_bloques_fijos(
            c.get("dia_fijo", ""), c.get("hora_inicio_fija", ""), c.get("hora_fin_fija", "")
        )
        if fijos:
            candidatos = fijos
            bloques = max(len(fijos), max(1, int(c["bloques_semanales"] or 1)))
        else:
            candidatos = sorted(
                disponibilidad.get(pid, []),
                key=lambda x: (_dias_ordenados(x[0]), _a_minutos(x[1]), _a_minutos(x[2])),
            )
            bloques = max(1, int(c["bloques_semanales"] or 1))

        if not candidatos:
            faltan = max(0, bloques - manuales_por_carga.get(cid, 0))
            if faltan:
                pendientes += faltan
                mensaje = f"Sin disponibilidad: {c['profesor']} — {c['materia']}."
                mensajes.append(mensaje)
                detalles.append({
                    "carga_id": cid, "motivo": "Sin disponibilidad", "detalle": mensaje,
                    "profesor": c["profesor"], "materia": c["materia"],
                })
            continue

        puestos = manuales_por_carga.get(cid, 0)
        ya_manuales = manuales_slots_por_carga.get(cid, set())

        # Elegir un ÚNICO ambiente libre (y NO bloqueado) para todos los bloques de esta materia
        salon_curso_id: Optional[int] = pref_id or manual_salon_por_carga.get(cid)
        if salon_curso_id is None and len(candidatos) > 1:
            pend_cands = [
                (d, i, f) for d, i, f in candidatos
                if (db.normalizar(d), str(i).strip(), str(f).strip()) not in ya_manuales
            ][:max(1, bloques - puestos)]
            if pend_cands:
                mejor = min(
                    salones,
                    key=lambda s: (
                        -sum(1 for d, i, f in pend_cands if _salon_libre_en(s, d, (i, f), salon_ocupado, bloqueos_activos)),
                        0 if (compartido and es_compartible(s["codigo"])) else (
                            1 if es_compartible(s["codigo"]) else 0
                        ),
                        uso_salon[int(s["id"])],
                        int(s["id"]),
                    ),
                )
                if any(_salon_libre_en(mejor, d, (i, f), salon_ocupado, bloqueos_activos) for d, i, f in pend_cands):
                    salon_curso_id = int(mejor["id"])

        for dia, ini, fin in candidatos:
            if puestos >= bloques:
                break
            if (db.normalizar(dia), str(ini).strip(), str(fin).strip()) in ya_manuales:
                continue
            franja = (ini, fin)

            # Respetar bloqueos activos de docente
            blq_doc = bloqueo_docente_en(c["profesor"], dia, franja, bloqueos_activos)
            if blq_doc is not None:
                detalles.append({
                    "carga_id": cid,
                    "motivo": "Docente bloqueado",
                    "detalle": (f"No se asignó «{c['materia']}» ({c['profesor']}) el {dia} {ini}–{fin}: "
                                f"{queries.descripcion_bloqueo(blq_doc)}."),
                    "profesor": c["profesor"], "materia": c["materia"],
                    "dia": dia, "desde": ini, "hasta": fin,
                })
                continue

            choque_prof = next((
                (d, o_ini, o_fin, o_mat) for d, o_ini, o_fin, o_mat in prof_ocupado[pid]
                if db.normalizar(d) == db.normalizar(dia)
                and _franjas_solapadas(franja, (o_ini, o_fin))
            ), None) if not compartido else None
            if choque_prof:
                detalles.append({
                    "carga_id": cid,
                    "motivo": "Docente ocupado",
                    "detalle": (f"{c['profesor']} ya imparte «{choque_prof[3]}» el {choque_prof[0]} "
                                f"{choque_prof[1]}–{choque_prof[2]}; el bloque de «{c['materia']}» "
                                f"({dia} {ini}–{fin}) se solapa y no se asignó automáticamente."),
                    "profesor": c["profesor"], "materia": c["materia"],
                    "dia": dia, "desde": ini, "hasta": fin,
                })
                continue

            orden = sorted(salones, key=lambda s: (
                0 if int(s["id"]) == pref_id else 1,
                0 if int(s["id"]) == salon_curso_id else 1,
                0 if (compartido and es_compartible(s["codigo"])) else (
                    1 if (es_compartible(s["codigo"]) and int(s["id"]) not in (pref_id, salon_curso_id)) else 0
                ),
                uso_salon[int(s["id"])],
                int(s["id"]),
            ))
            elegido = None
            for s in orden:
                if _salon_libre_en(s, dia, franja, salon_ocupado, bloqueos_activos):
                    elegido = s
                    break
            if elegido is None:
                detalles.append({
                    "carga_id": cid,
                    "motivo": "Sin ambiente libre",
                    "detalle": (f"No hay ambiente disponible para {c['materia']} "
                                f"({c['profesor']}) el {dia} {ini}–{fin}: todos los ambientes "
                                f"están ocupados o bloqueados en ese horario."),
                    "profesor": c["profesor"], "materia": c["materia"],
                    "dia": dia, "desde": ini, "hasta": fin,
                })
                continue

            sid = int(elegido["id"])
            if salon_curso_id is None:
                salon_curso_id = sid
            db.execute("""INSERT INTO asignaciones_horario
                (carga_id,profesor_id,materia_id,salon_id,dia,hora_inicio,hora_fin,estado)
                VALUES (?,?,?,?,?,?,?,'Auto')""",
                (cid, pid, mid, sid, dia, ini, fin))
            prof_ocupado[pid].append((dia, ini, fin, c["materia"]))
            salon_ocupado[sid].append((dia, ini, fin))
            uso_salon[sid] += 1
            asignados += 1
            puestos += 1

        if puestos < bloques:
            pendientes += bloques - puestos
            mensaje = f"Faltaron {bloques - puestos} bloque(s) para {c['materia']} ({c['profesor']})."
            mensajes.append(mensaje)
            detalles.append({
                "carga_id": cid, "motivo": "Bloques pendientes", "detalle": mensaje,
                "profesor": c["profesor"], "materia": c["materia"],
            })

    if not mensajes:
        mensajes.append(f"OK: {asignados} clases asignadas sin conflictos.")
    return {"asignados": asignados, "pendientes": pendientes,
            "mensajes": mensajes, "detalles": detalles}


def validar_cambio_manual(
    asignacion_id: int,
    salon_id: int,
    dia: str,
    ini: str,
    fin: str,
    profesor_id: Optional[int] = None,
    compartido: bool = False,
) -> Tuple[bool, str]:
    actual = db.query("SELECT * FROM asignaciones_horario WHERE id=?", (int(asignacion_id),))
    if not actual:
        return False, "La asignación no existe."
    if not dia or not ini or not fin or _a_minutos(ini) >= _a_minutos(fin):
        return False, "El rango horario no es válido (la hora de inicio debe ser menor a la de fin)."
    salon = db.query("SELECT id, codigo FROM salones WHERE id=?", (int(salon_id),))
    if not salon:
        return False, "El ambiente seleccionado no existe."

    prof = int(profesor_id) if profesor_id is not None else int(actual[0]["profesor_id"])
    prof_row = db.query("SELECT id, nombre FROM profesores WHERE id=?", (prof,))
    if not prof_row:
        return False, "El docente seleccionado no existe."

    # Validar contra bloqueos activos (piso/ambiente/todos/docente)
    bloqueos = queries.obtener_bloqueos(solo_activos=True)
    blq_s = bloqueo_salon_en(salon[0]["codigo"], dia, (ini, fin), bloqueos)
    if blq_s is not None:
        return False, f"Bloqueo activo: {queries.descripcion_bloqueo(blq_s)}."
    blq_d = bloqueo_docente_en(prof_row[0]["nombre"], dia, (ini, fin), bloqueos)
    if blq_d is not None:
        return False, f"Bloqueo activo: {queries.descripcion_bloqueo(blq_d)}."

    otras = db.query("""
        SELECT a.id, a.profesor_id, a.salon_id, a.dia, a.hora_inicio, a.hora_fin,
               p.nombre AS profesor, m.nombre AS materia, s.codigo AS ambiente
        FROM asignaciones_horario a
        JOIN profesores p ON p.id=a.profesor_id
        JOIN materias m ON m.id=a.materia_id
        JOIN salones s ON s.id=a.salon_id
        WHERE a.id != ?
    """, (int(asignacion_id),))

    dia_n = db.normalizar(dia)
    for o in otras:
        if db.normalizar(o["dia"]) != dia_n:
            continue
        if not _franjas_solapadas((ini, fin), (o["hora_inicio"], o["hora_fin"])):
            continue
        if int(o["salon_id"]) == int(salon_id) and not es_compartible(salon[0]["codigo"]):
            return (
                False,
                f"El ambiente {salon[0]['codigo']} ya está ocupado el {_canon_dia(dia)} "
                f"{o['hora_inicio']}–{o['hora_fin']} por «{o['materia']}» ({o['profesor']}).",
            )
        if int(o["profesor_id"]) == prof and not compartido:
            return (
                False,
                f"El docente {prof_row[0]['nombre']} ya dicta «{o['materia']}» el {_canon_dia(dia)} "
                f"{o['hora_inicio']}–{o['hora_fin']} ({o['ambiente']}).",
            )
    return True, ""


def editar_asignacion(
    asignacion_id: int,
    salon_id: int,
    dia: str,
    ini: str,
    fin: str,
    profesor_id: Optional[int] = None,
    seccion: Optional[str] = None,
    compartido: Optional[bool] = None,
    aplicar_toda_materia: bool = False,
) -> Tuple[bool, str]:
    actual_rows = db.query("SELECT * FROM asignaciones_horario WHERE id=?", (int(asignacion_id),))
    if not actual_rows:
        return False, "El bloque horario no existe."
    actual = actual_rows[0]
    cid_orig = int(actual["carga_id"])
    mid = int(actual["materia_id"])
    carga_rows = db.query("SELECT * FROM carga_academica WHERE id=?", (cid_orig,))
    carga_orig = carga_rows[0] if carga_rows else {}

    nuevo_prof_id = int(profesor_id) if profesor_id is not None else int(actual["profesor_id"])
    nueva_seccion = (seccion or "").strip() or (carga_orig.get("seccion") or "Sección A")
    comp_bool = bool(compartido) if compartido is not None else bool(str(carga_orig.get("compartidos") or "").strip())
    comp_txt = "COMPARTIDOS" if comp_bool else ""
    dia_canon = _canon_dia(dia)

    ok, msg = validar_cambio_manual(
        asignacion_id, salon_id, dia_canon, ini, fin,
        profesor_id=nuevo_prof_id, compartido=comp_bool,
    )
    if not ok:
        return False, msg

    salon_cod = db.query("SELECT codigo FROM salones WHERE id=?", (int(salon_id),))[0]["codigo"]
    respaldo = db.respaldar_bd("antes_editar_bloque")
    try:
        disp = db.query(
            "SELECT id FROM disponibilidades WHERE profesor_id=? AND dia=? AND hora_inicio=? AND hora_fin=? LIMIT 1",
            (nuevo_prof_id, dia_canon, ini, fin),
        )
        if not disp:
            db.execute(
                "INSERT INTO disponibilidades (profesor_id,dia,hora_inicio,hora_fin) VALUES (?,?,?,?)",
                (nuevo_prof_id, dia_canon, ini, fin),
            )

        hermanos = db.query("SELECT id FROM asignaciones_horario WHERE carga_id=?", (cid_orig,))
        cambio_identidad = (
            nuevo_prof_id != int(actual["profesor_id"])
            or nueva_seccion != (carga_orig.get("seccion") or "Sección A")
        )

        db.execute(
            """UPDATE asignaciones_horario
               SET profesor_id=?, salon_id=?, dia=?, hora_inicio=?, hora_fin=?, estado='Manual'
               WHERE id=?""",
            (nuevo_prof_id, int(salon_id), dia_canon, ini, fin, int(asignacion_id)),
        )

        if not cambio_identidad:
            db.execute(
                "UPDATE carga_academica SET salon_preferido=?, compartidos=? WHERE id=?",
                (salon_cod, comp_txt, cid_orig),
            )
            _sincronizar_carga_desde_asignaciones(cid_orig)
        elif aplicar_toda_materia or len(hermanos) <= 1:
            existente = db.query(
                "SELECT id FROM carga_academica WHERE profesor_id=? AND materia_id=? AND seccion=? LIMIT 1",
                (nuevo_prof_id, mid, nueva_seccion),
            )
            if existente and int(existente[0]["id"]) != cid_orig:
                cid_dest = int(existente[0]["id"])
                for h in hermanos:
                    db.execute(
                        "UPDATE asignaciones_horario SET carga_id=?, profesor_id=? WHERE id=?",
                        (cid_dest, nuevo_prof_id, int(h["id"])),
                    )
                db.execute(
                    "UPDATE carga_academica SET salon_preferido=?, compartidos=? WHERE id=?",
                    (salon_cod, comp_txt, cid_dest),
                )
                _sincronizar_carga_desde_asignaciones(cid_dest)
                _sincronizar_carga_desde_asignaciones(cid_orig)
            else:
                db.execute(
                    "UPDATE carga_academica SET profesor_id=?, seccion=?, salon_preferido=?, compartidos=? WHERE id=?",
                    (nuevo_prof_id, nueva_seccion, salon_cod, comp_txt, cid_orig),
                )
                for h in hermanos:
                    if int(h["id"]) != int(asignacion_id):
                        db.execute("UPDATE asignaciones_horario SET profesor_id=? WHERE id=?",
                                   (nuevo_prof_id, int(h["id"])))
                _sincronizar_carga_desde_asignaciones(cid_orig)
        else:
            existente = db.query(
                "SELECT id FROM carga_academica WHERE profesor_id=? AND materia_id=? AND seccion=? LIMIT 1",
                (nuevo_prof_id, mid, nueva_seccion),
            )
            if existente:
                cid_dest = int(existente[0]["id"])
            else:
                cid_dest = int(db.execute(
                    """INSERT INTO carga_academica
                       (profesor_id,materia_id,seccion,bloques_semanales,salon_preferido,
                        dia_fijo,hora_inicio_fija,hora_fin_fija,compartidos)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (nuevo_prof_id, mid, nueva_seccion, 1, salon_cod, dia_canon, ini, fin, comp_txt),
                ))
                if not cid_dest:
                    f_c = db.query(
                        "SELECT id FROM carga_academica WHERE profesor_id=? AND materia_id=? AND seccion=? LIMIT 1",
                        (nuevo_prof_id, mid, nueva_seccion),
                    )
                    cid_dest = int(f_c[0]["id"]) if f_c else cid_orig
            db.execute("UPDATE asignaciones_horario SET carga_id=? WHERE id=?", (cid_dest, int(asignacion_id)))
            _sincronizar_carga_desde_asignaciones(cid_orig)
            _sincronizar_carga_desde_asignaciones(cid_dest)

        return True, "Bloque horario actualizado correctamente."
    except Exception as exc:
        db.restaurar_bd(respaldo)
        return False, f"Error al actualizar el bloque (sin cambios en BD): {exc}"


def eliminar_asignacion(asignacion_id: int) -> Tuple[bool, str, Optional[int]]:
    filas = db.query("""
        SELECT a.id, a.carga_id, a.dia, a.hora_inicio, a.hora_fin,
               m.nombre AS materia, m.carrera_id AS carrera_id, ca.seccion AS seccion
        FROM asignaciones_horario a
        JOIN materias m ON m.id=a.materia_id
        LEFT JOIN carga_academica ca ON ca.id=a.carga_id
        WHERE a.id=?
    """, (int(asignacion_id),))
    if not filas:
        return False, "El bloque que intentó eliminar ya no existe.", None

    f = filas[0]
    cid = int(f["carga_id"])
    car_id = int(f["carrera_id"]) if f.get("carrera_id") else None
    respaldo = db.respaldar_bd("antes_eliminar_bloque")
    try:
        db.execute("DELETE FROM asignaciones_horario WHERE id=?", (int(asignacion_id),))
        restantes = _sincronizar_carga_desde_asignaciones(cid)
        detalle_rest = (
            f"Quedan {restantes} bloque(s) de esta materia."
            if restantes > 0
            else "Era el último bloque de esta sección, por lo que se retiró del horario."
        )
        return (
            True,
            f"Bloque eliminado: «{f['materia']}» ({f['dia']} {f['hora_inicio']}–{f['hora_fin']}). {detalle_rest}",
            car_id,
        )
    except Exception as exc:
        db.restaurar_bd(respaldo)
        return False, f"No se pudo eliminar el bloque: {exc}", car_id


def eliminar_carga_completa(carga_id: int) -> Tuple[bool, str, Optional[int]]:
    filas = db.query("""
        SELECT ca.id, ca.seccion, m.nombre AS materia, m.carrera_id AS carrera_id, p.nombre AS profesor
        FROM carga_academica ca
        JOIN materias m ON m.id=ca.materia_id
        JOIN profesores p ON p.id=ca.profesor_id
        WHERE ca.id=?
    """, (int(carga_id),))
    if not filas:
        return False, "La materia/sección seleccionada ya no existe.", None

    f = filas[0]
    car_id = int(f["carrera_id"]) if f.get("carrera_id") else None
    respaldo = db.respaldar_bd("antes_eliminar_carga")
    try:
        cant = len(db.query("SELECT id FROM asignaciones_horario WHERE carga_id=?", (int(carga_id),)))
        db.borrar_donde("asignaciones_horario", "carga_id", int(carga_id))
        db.execute("DELETE FROM carga_academica WHERE id=?", (int(carga_id),))
        return (
            True,
            f"Materia eliminada del horario: «{f['materia']}» ({f['seccion']} · {f['profesor']}, "
            f"{cant} bloque(s)). Las demás materias permanecen intactas.",
            car_id,
        )
    except Exception as exc:
        db.restaurar_bd(respaldo)
        return False, f"No se pudo eliminar la materia: {exc}", car_id


def eliminar_horarios_carrera(carrera_id: int) -> Tuple[bool, str]:
    """Elimina TODOS los bloques y cargas académicas de UNA carrera/mención específica.

    Conserva intactos la carrera, su pensum, su catálogo de materias, los docentes,
    los ambientes y los horarios de todas las demás carreras. Crea respaldo previo.
    """
    car = db.query("SELECT id, nombre FROM carreras WHERE id=? LIMIT 1", (int(carrera_id),))
    if not car:
        return False, "La carrera seleccionada no existe."
    nombre_car = car[0]["nombre"]

    materias = db.query("SELECT id FROM materias WHERE carrera_id=?", (int(carrera_id),))
    mat_ids = [int(m["id"]) for m in materias]
    if not mat_ids:
        return True, f"«{nombre_car}» no tiene clases programadas actualmente."

    marcadores = ",".join("?" for _ in mat_ids)
    cargas = db.query(
        f"SELECT id FROM carga_academica WHERE materia_id IN ({marcadores})",
        mat_ids,
    )
    carga_ids = [int(c["id"]) for c in cargas]
    asigs = db.query(
        f"SELECT id FROM asignaciones_horario WHERE materia_id IN ({marcadores})",
        mat_ids,
    )
    if not carga_ids and not asigs:
        return True, f"«{nombre_car}» no tiene clases ni cargas académicas que eliminar."

    respaldo = db.respaldar_bd("antes_vaciar_carrera")
    try:
        for mid in mat_ids:
            db.borrar_donde("asignaciones_horario", "materia_id", mid)
        for cid in carga_ids:
            db.borrar_donde("asignaciones_horario", "carga_id", cid)
            db.execute("DELETE FROM carga_academica WHERE id=?", (cid,))
        return (
            True,
            f"Horario vaciado para «{nombre_car}»: se eliminaron {len(asigs)} bloque(s) y "
            f"{len(carga_ids)} ficha(s) de carga. Se conservaron el pensum, materias, docentes, "
            f"ambientes y los horarios de todas las demás carreras.",
        )
    except Exception as exc:
        db.restaurar_bd(respaldo)
        return False, f"No se pudo vaciar el horario de «{nombre_car}» (se restauró el respaldo): {exc}"


def conflictos() -> List[Dict]:
    filas = db.query("""SELECT a.*, p.nombre AS profesor, s.codigo AS ambiente, m.nombre AS materia,
        m.carrera_id AS carrera_id, c.nombre AS carrera, ca.seccion AS seccion,
        ca.dia_fijo AS dia_fijo
        FROM asignaciones_horario a
        JOIN profesores p ON p.id=a.profesor_id
        JOIN salones s ON s.id=a.salon_id
        JOIN materias m ON m.id=a.materia_id
        LEFT JOIN carreras c ON c.id=m.carrera_id
        LEFT JOIN carga_academica ca ON ca.id=a.carga_id""")
    resultado = []
    for i, a in enumerate(filas):
        for b in filas[i + 1:]:
            if db.normalizar(a["dia"]) != db.normalizar(b["dia"]):
                continue
            if not _franjas_solapadas((a["hora_inicio"], a["hora_fin"]), (b["hora_inicio"], b["hora_fin"])):
                continue
            motivos = []
            if int(a["profesor_id"]) == int(b["profesor_id"]):
                motivos.append("docente")
            if int(a["salon_id"]) == int(b["salon_id"]) and not es_compartible(a["ambiente"]):
                motivos.append("ambiente")
            if not motivos:
                continue
            desde = _hora_mayor(a["hora_inicio"], b["hora_inicio"])
            hasta = _hora_menor(a["hora_fin"], b["hora_fin"])

            def _quien(f: Dict) -> str:
                carrera = f.get("carrera") or "carrera sin asignar"
                seccion = f.get("seccion") or "—"
                return (f"{f['materia']} ({f['profesor']}, {f['ambiente']}, "
                        f"{carrera}, secc. {seccion})")

            manual = ("Manual" in (str(a.get("estado") or ""), str(b.get("estado") or ""))
                      or bool(a.get("dia_fijo")) or bool(b.get("dia_fijo")))
            resultado.append({
                "a": a, "b": b,
                "motivo": " y ".join(motivos),
                "motivos": motivos,
                "dia": a["dia"],
                "desde": desde,
                "hasta": hasta,
                "ids": [int(a["id"]), int(b["id"])],
                "carrera_id": int(a["carrera_id"]) if a.get("carrera_id") else None,
                "b_carrera_id": int(b["carrera_id"]) if b.get("carrera_id") else None,
                "detalle": (f"{'/'.join(motivos).capitalize()} el {a['dia']} {desde}–{hasta}: "
                            f"{_quien(a)} vs {_quien(b)}."),
                "sugerencia": "manual" if manual else "auto",
            })
    return resultado
