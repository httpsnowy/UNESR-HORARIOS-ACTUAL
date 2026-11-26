"""Consultas de dominio reutilizables por la web y los reportes."""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from . import db

CLAVE_CONFIG_FRANJAS = "franjas_horario"
CLAVE_CONFIG_BLOQUEOS = "bloqueos_horario"

FRANJAS_POR_DEFECTO: List[List[str]] = [
    ["07:00", "07:45"],
    ["07:45", "08:30"],
    ["08:30", "09:15"],
    ["09:20", "10:05"],
    ["10:05", "10:50"],
    ["10:50", "11:35"],
    ["11:35", "12:15"],
    ["12:30", "13:15"],
    ["13:15", "14:00"],
    ["14:10", "14:55"],
    ["14:55", "15:35"],
    ["15:40", "16:25"],
    ["16:25", "17:10"],
    ["17:10", "18:00"],
    ["18:00", "18:45"],
]
FRANJAS_45MIN = FRANJAS_POR_DEFECTO

SQL_OFERTAS = """
SELECT a.id, a.carga_id, a.dia, a.hora_inicio, a.hora_fin, a.estado,
       c.id AS carrera_id, c.nombre AS carrera,
       f.nombre AS facultad,
       p.id AS profesor_id, p.nombre AS profesor,
       m.id AS materia_id, m.nombre AS materia, m.codigo AS codigo,
       s.id AS salon_id, s.codigo AS ambiente,
       ca.seccion, ca.compartidos
FROM asignaciones_horario a
JOIN carga_academica ca ON ca.id=a.carga_id
JOIN profesores p ON p.id=a.profesor_id
JOIN materias m ON m.id=a.materia_id
JOIN carreras c ON c.id=m.carrera_id
JOIN facultades f ON f.id=c.facultad_id
JOIN salones s ON s.id=a.salon_id
"""


def oferta(facultad_id: Optional[int] = None, carrera_id: Optional[int] = None,
           profesor_id: Optional[int] = None, dia: Optional[str] = None) -> List[Dict]:
    conditions, params = [], []
    if facultad_id:
        conditions.append("f.id=?"); params.append(facultad_id)
    if carrera_id:
        conditions.append("c.id=?"); params.append(carrera_id)
    if profesor_id:
        conditions.append("p.id=?"); params.append(profesor_id)
    sql = SQL_OFERTAS
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.nombre, a.dia, a.hora_inicio, p.nombre, m.nombre"
    filas = db.query(sql, params)
    conteo_por_carga: Dict[int, int] = {}
    for f in filas:
        cid = int(f.get("carga_id") or 0)
        conteo_por_carga[cid] = conteo_por_carga.get(cid, 0) + 1
    for f in filas:
        f["bloques_en_carga"] = conteo_por_carga.get(int(f.get("carga_id") or 0), 1)
    if dia:
        dia_norm = db.normalizar(dia)
        filas = [f for f in filas if db.normalizar(f.get("dia")) == dia_norm]
    return filas


def carreras_con_pensum() -> List[Dict]:
    carreras = db.query("""
        SELECT c.id, c.nombre, c.codigo, f.nombre AS facultad
        FROM carreras c JOIN facultades f ON f.id=c.facultad_id
        ORDER BY f.nombre, c.nombre
    """)
    planes = db.query("""
        SELECT carrera_id, codigo, nombre, unidad_credito, horas_teoria,
               horas_practica, ciclo, opcionalidad, tecnica, prelacion
        FROM planes_estudio ORDER BY ciclo, codigo, nombre
    """)
    materias = db.query("""
        SELECT carrera_id, codigo, nombre, semestre AS ciclo, unidad_credito
        FROM materias ORDER BY semestre, nombre
    """)
    planes_por_car: Dict[int, List[Dict]] = {}
    for p in planes:
        planes_por_car.setdefault(int(p["carrera_id"]), []).append(dict(p))

    mats_por_car: Dict[int, List[Dict]] = {}
    for m in materias:
        mats_por_car.setdefault(int(m["carrera_id"]), []).append(dict(m))

    resultado = []
    for c in carreras:
        cid = int(c["id"])
        p_lista = planes_por_car.get(cid, [])
        m_lista = mats_por_car.get(cid, [])
        if p_lista:
            combinadas = list(p_lista)
            vistos = {db.normalizar(x.get("nombre")) for x in combinadas}
            for m in m_lista:
                if db.normalizar(m.get("nombre")) not in vistos:
                    combinadas.append(m)
                    vistos.add(db.normalizar(m.get("nombre")))
            fuente = "Plan de estudio"
        else:
            combinadas = list(m_lista)
            fuente = "Catálogo de oferta"
        resultado.append({
            "id": cid,
            "nombre": c["nombre"],
            "facultad": c["facultad"],
            "codigo": c.get("codigo") or "",
            "materias": combinadas,
            "fuente": fuente,
        })
    return resultado


def detectar_carreras_duplicadas() -> int:
    carreras = db.query("SELECT id, nombre FROM carreras")
    claves = set()
    dups = 0
    for c in carreras:
        k = db._clave_carrera_suave(db.nombre_carrera_canonico(c["nombre"]))
        if k in claves:
            dups += 1
        else:
            claves.add(k)
    return dups


def carreras_sin_pensum() -> List[str]:
    return [c["nombre"] for c in carreras_con_pensum() if not c["materias"]]


def estado_carga_carrera(carrera_id: int) -> Dict:
    carrera_id = int(carrera_id)
    pensum = next((c["materias"] for c in carreras_con_pensum()
                   if c["id"] == carrera_id), [])

    materias = db.query("SELECT id, nombre FROM materias WHERE carrera_id = ?",
                        (carrera_id,))
    mat_ids = [int(m["id"]) for m in materias]
    if mat_ids:
        marcadores = ",".join("?" for _ in mat_ids)
        carga = db.query(
            f"SELECT id, materia_id FROM carga_academica WHERE materia_id IN ({marcadores})",
            mat_ids)
    else:
        carga = []
    carga_ids = [int(c["id"]) for c in carga]
    if carga_ids:
        marcadores = ",".join("?" for _ in carga_ids)
        asignaciones = db.query(
            f"SELECT id FROM asignaciones_horario WHERE carga_id IN ({marcadores})",
            carga_ids)
    else:
        asignaciones = []

    con_docente = {db.normalizar(m["nombre"]) for m in materias
                   if int(m["id"]) in {int(c["materia_id"]) for c in carga}}
    pendientes = [m for m in pensum
                  if db.normalizar(m.get("nombre")) not in con_docente]
    return {
        "pensum": pensum,
        "total_uc": sum(int(m.get("unidad_credito") or 0) for m in pensum),
        "materias_pensum": len(pensum),
        "materias_con_docente": len(pensum) - len(pendientes),
        "pendientes": pendientes,
        "carga": len(carga),
        "asignaciones": len(asignaciones),
        "sin_clases": not asignaciones,
    }


def horario_por_carrera(carrera_id: int, dia: Optional[str] = None,
                        profesor_id: Optional[int] = None) -> "OrderedDict[str, List[Dict]]":
    filas = oferta(carrera_id=carrera_id, dia=dia, profesor_id=profesor_id)
    por_dia: OrderedDict[str, List[Dict]] = OrderedDict()
    for d in db.DIAS_ORDEN:
        por_dia[d] = []
    for fila in filas:
        d_canon = next((d for d in db.DIAS_ORDEN if db.normalizar(d) == db.normalizar(fila["dia"])), fila["dia"])
        por_dia.setdefault(d_canon, []).append(fila)
    for d in por_dia:
        por_dia[d].sort(key=lambda r: (_hora(r["hora_inicio"]), _hora(r["hora_fin"]), r["profesor"], r["materia"]))
    return por_dia


def cuadro_horario(carrera_id: int, dia: Optional[str] = None,
                   profesor_id: Optional[int] = None) -> Dict:
    filas = oferta(carrera_id=carrera_id, dia=dia, profesor_id=profesor_id)
    dias = list(db.DIAS_ORDEN[:6])
    for fila in filas:
        dia_norm = db.normalizar(fila["dia"])
        if not any(db.normalizar(d) == dia_norm for d in dias):
            dias.append(fila["dia"])
    franjas = sorted({(f["hora_inicio"], f["hora_fin"]) for f in filas},
                     key=lambda fr: (_hora(fr[0]), _hora(fr[1])))
    celdas: Dict[str, Dict[str, List[Dict]]] = {d: {} for d in dias}
    celdas_franja: Dict[str, Dict[str, List[Dict]]] = {d: {} for d in dias}
    for fila in filas:
        dia_fila = next(
            (d for d in dias if db.normalizar(d) == db.normalizar(fila["dia"])),
            fila["dia"],
        )
        celdas.setdefault(dia_fila, {}).setdefault(fila["hora_inicio"], []).append(fila)
        clave_franja = f"{fila['hora_inicio']}-{fila['hora_fin']}"
        celdas_franja.setdefault(dia_fila, {}).setdefault(clave_franja, []).append(fila)
    for dia_key in celdas:
        for franja in celdas[dia_key]:
            celdas[dia_key][franja].sort(key=lambda r: (r["profesor"], r["materia"], r["ambiente"]))
    for dia_key in celdas_franja:
        for franja in celdas_franja[dia_key]:
            celdas_franja[dia_key][franja].sort(key=lambda r: (r["profesor"], r["materia"], r["ambiente"]))
    return {
        "dias": dias,
        "franjas": franjas,
        "celdas": celdas,
        "celdas_franja": celdas_franja,
        "total": len(filas),
    }


def _hora(hhmm: str) -> int:
    try:
        h, m = str(hhmm).strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 9999


def _normalizar_hhmm(valor: Any) -> str:
    texto = str(valor or "").strip()
    if ":" not in texto:
        return ""
    partes = texto.split(":")
    try:
        h, m = int(partes[0]), int(partes[1])
    except (ValueError, IndexError):
        return ""
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return ""
    return f"{h:02d}:{m:02d}"


def _canon_dia(dia: Any) -> str:
    dn = db.normalizar(dia)
    if dn in ("TODOS", "TODOS LOS DIAS"):
        return "Todos"
    for nombre in db.DIAS_ORDEN:
        if db.normalizar(nombre) == dn:
            return nombre
    return str(dia or "").strip()


def _orden_dia(dia: Any) -> int:
    dn = db.normalizar(dia)
    if dn in ("TODOS", "TODOS LOS DIAS"):
        return -1
    for idx, nombre in enumerate(db.DIAS_ORDEN):
        if db.normalizar(nombre) == dn:
            return idx
    return len(db.DIAS_ORDEN)


def _franjas_solapan(a: Tuple[str, str], b: Tuple[str, str]) -> bool:
    return max(_hora(a[0]), _hora(b[0])) < min(_hora(a[1]), _hora(b[1]))


def _entero_seguro(valor: Any) -> int:
    try:
        if valor is None or str(valor).strip() == "":
            return 0
        return max(0, int(float(str(valor).strip())))
    except (TypeError, ValueError):
        return 0


def _normalizar_lista_franjas(franjas: Any) -> List[List[str]]:
    limpias: List[List[str]] = []
    vistos = set()
    if not isinstance(franjas, (list, tuple)):
        return []
    for item in franjas:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        ini = _normalizar_hhmm(item[0])
        fin = _normalizar_hhmm(item[1])
        if not ini or not fin or _hora(ini) >= _hora(fin):
            continue
        clave = (ini, fin)
        if clave in vistos:
            continue
        vistos.add(clave)
        limpias.append([ini, fin])
    limpias.sort(key=lambda fr: (_hora(fr[0]), _hora(fr[1])))
    return limpias


def obtener_franjas_sistema() -> List[List[str]]:
    raw = db.get_config(CLAVE_CONFIG_FRANJAS, "")
    if raw:
        try:
            datos = json.loads(raw)
            limpias = _normalizar_lista_franjas(datos)
            if limpias:
                return limpias
        except Exception:
            pass
    return [list(f) for f in FRANJAS_POR_DEFECTO]


def guardar_franjas_sistema(franjas: Any) -> List[List[str]]:
    limpias = _normalizar_lista_franjas(franjas)
    if not limpias:
        raise ValueError("Debe mantener al menos una franja horaria válida (hora de inicio menor a hora de fin).")
    db.set_config(CLAVE_CONFIG_FRANJAS, json.dumps(limpias, ensure_ascii=False))
    return limpias


def restaurar_franjas_por_defecto() -> List[List[str]]:
    db.delete_config(CLAVE_CONFIG_FRANJAS)
    return [list(f) for f in FRANJAS_POR_DEFECTO]


# ──────────────────── Bloqueos de día y hora (persistentes) ────────────────────

TIPOS_BLOQUEO = ("piso", "ambiente", "docente", "todos")


def _normalizar_bloqueo(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    tipo = str(raw.get("tipo") or "piso").strip().lower()
    if tipo not in TIPOS_BLOQUEO:
        return None
    objetivo = " ".join(str(raw.get("objetivo") or "").strip().split())
    if tipo == "todos":
        objetivo = "Todos los ambientes"
    elif tipo == "ambiente":
        objetivo = objetivo.upper()
    elif not objetivo:
        return None

    dia = _canon_dia(raw.get("dia") or "")
    if not dia:
        return None
    todo_el_dia = bool(raw.get("todo_el_dia"))
    if todo_el_dia:
        ini, fin = "00:00", "23:59"
    else:
        ini = _normalizar_hhmm(raw.get("hora_inicio"))
        fin = _normalizar_hhmm(raw.get("hora_fin"))
        if not ini or not fin or _hora(ini) >= _hora(fin):
            return None

    bid = str(raw.get("id") or "").strip() or f"blq_{int(time.time() * 1000)}"
    motivo = " ".join(str(raw.get("motivo") or "").strip().split())
    activo = bool(raw.get("activo", True))
    return {
        "id": bid,
        "activo": activo,
        "tipo": tipo,
        "objetivo": objetivo,
        "dia": dia,
        "todo_el_dia": todo_el_dia,
        "hora_inicio": ini,
        "hora_fin": fin,
        "motivo": motivo,
    }


def obtener_bloqueos(solo_activos: bool = False) -> List[Dict[str, Any]]:
    """Devuelve todas las reglas de bloqueo guardadas en ``configuracion``."""
    raw = db.get_config(CLAVE_CONFIG_BLOQUEOS, "")
    if not raw:
        return []
    try:
        datos = json.loads(raw)
    except Exception:
        return []
    if not isinstance(datos, list):
        return []
    salida: List[Dict[str, Any]] = []
    for item in datos:
        limpio = _normalizar_bloqueo(item)
        if not limpio:
            continue
        if solo_activos and not limpio["activo"]:
            continue
        salida.append(limpio)
    salida.sort(key=lambda b: (0 if b["activo"] else 1, _orden_dia(b["dia"]), _hora(b["hora_inicio"]), b["objetivo"]))
    return salida


def _escribir_bloqueos(lista: List[Dict[str, Any]]) -> None:
    db.set_config(CLAVE_CONFIG_BLOQUEOS, json.dumps(lista, ensure_ascii=False))


def guardar_bloqueo(
    *,
    bloqueo_id: Optional[str] = None,
    tipo: str,
    objetivo: str,
    dia: str,
    todo_el_dia: bool = False,
    hora_inicio: str = "",
    hora_fin: str = "",
    motivo: str = "",
    activo: bool = True,
) -> Dict[str, Any]:
    """Crea o actualiza un bloqueo de día/hora en ``configuracion``."""
    tipo_clean = str(tipo or "piso").strip().lower()
    if tipo_clean not in TIPOS_BLOQUEO:
        raise ValueError("Tipo de bloqueo inválido.")
    obj_clean = " ".join(str(objetivo or "").strip().split())
    if tipo_clean == "todos":
        obj_clean = "Todos los ambientes"
    elif tipo_clean == "ambiente":
        obj_clean = obj_clean.upper()
    elif not obj_clean:
        raise ValueError("Debe elegir qué piso, ambiente o docente desea bloquear.")

    dia_clean = _canon_dia(dia)
    if not dia_clean:
        raise ValueError("Debe seleccionar un día.")

    if todo_el_dia:
        ini_clean, fin_clean = "00:00", "23:59"
    else:
        ini_clean = _normalizar_hhmm(hora_inicio)
        fin_clean = _normalizar_hhmm(hora_fin)
        if not ini_clean or not fin_clean or _hora(ini_clean) >= _hora(fin_clean):
            raise ValueError("El rango horario del bloqueo no es válido (Desde debe ser menor que Hasta).")

    actuales = obtener_bloqueos(solo_activos=False)
    bid = str(bloqueo_id or "").strip()
    if not bid:
        base_id = f"blq_{int(time.time() * 1000)}"
        existentes_ids = {b["id"] for b in actuales}
        suf = 1
        bid = base_id
        while bid in existentes_ids:
            bid = f"{base_id}_{suf}"
            suf += 1

    nuevo = {
        "id": bid,
        "activo": bool(activo),
        "tipo": tipo_clean,
        "objetivo": obj_clean,
        "dia": dia_clean,
        "todo_el_dia": bool(todo_el_dia),
        "hora_inicio": ini_clean,
        "hora_fin": fin_clean,
        "motivo": " ".join(str(motivo or "").strip().split()),
    }

    reemplazado = False
    for idx, b in enumerate(actuales):
        if b["id"] == bid:
            actuales[idx] = nuevo
            reemplazado = True
            break
    if not reemplazado:
        actuales.append(nuevo)
    _escribir_bloqueos(actuales)
    return nuevo


def alternar_bloqueo(bloqueo_id: str) -> Optional[Dict[str, Any]]:
    """Activa o desactiva un bloqueo existente sin borrarlo."""
    actuales = obtener_bloqueos(solo_activos=False)
    encontrado = None
    for b in actuales:
        if b["id"] == str(bloqueo_id):
            b["activo"] = not bool(b["activo"])
            encontrado = b
            break
    if encontrado is not None:
        _escribir_bloqueos(actuales)
    return encontrado


def eliminar_bloqueo(bloqueo_id: str) -> bool:
    actuales = obtener_bloqueos(solo_activos=False)
    nuevos = [b for b in actuales if b["id"] != str(bloqueo_id)]
    if len(nuevos) == len(actuales):
        return False
    _escribir_bloqueos(nuevos)
    return True


def descripcion_bloqueo(b: Dict[str, Any]) -> str:
    rango = "Todo el día" if b.get("todo_el_dia") else f"{b.get('hora_inicio')}–{b.get('hora_fin')}"
    base = f"{b.get('objetivo')} bloqueado ({b.get('dia')} · {rango})"
    if b.get("motivo"):
        base += f" — {b['motivo']}"
    return base


def profesores() -> List[Dict]:
    return db.query("SELECT id,nombre,cedula,email,condicion,mencion FROM profesores ORDER BY nombre")


def salones() -> List[Dict]:
    return db.ambientes_oficiales(
        db.query("SELECT id,codigo,capacidad,edificio,es_camillas FROM salones"))


def facultades() -> List[Dict]:
    return db.query("SELECT id,nombre FROM facultades ORDER BY nombre")


def asignaciones_profesor(profesor_id: int) -> List[Dict]:
    return oferta(profesor_id=profesor_id)


def max_horas_materia(carrera_nombre: str, materia_nombre: str, creditos_form: Any = 0) -> int:
    mat_norm = db.normalizar(materia_nombre)
    if not mat_norm:
        return 0

    car_row = db.buscar_carrera_existente(carrera_nombre)
    car_id: Optional[int] = int(car_row["id"]) if car_row else None

    if car_id is not None:
        uc_plan = 0
        for p in db.query(
            "SELECT nombre, horas_teoria, horas_practica, unidad_credito "
            "FROM planes_estudio WHERE carrera_id=?",
            (car_id,),
        ):
            if db.normalizar(p.get("nombre")) == mat_norm:
                total = _entero_seguro(p.get("horas_teoria")) + _entero_seguro(p.get("horas_practica"))
                if total > 0:
                    return total
                uc_p = _entero_seguro(p.get("unidad_credito"))
                if uc_p > 0:
                    uc_plan = uc_p
        if uc_plan > 0:
            return uc_plan

        for m in db.query("SELECT nombre, unidad_credito FROM materias WHERE carrera_id=?", (car_id,)):
            if db.normalizar(m.get("nombre")) == mat_norm:
                uc_m = _entero_seguro(m.get("unidad_credito"))
                if uc_m > 0:
                    return uc_m

    uc_f = _entero_seguro(creditos_form)
    return uc_f if uc_f > 0 else 0


def _disponibilidades_por_profesor(lista_profesores: List[Dict]) -> Dict[str, Dict[str, Any]]:
    prof_clave_por_id = {
        int(p["id"]): db.normalizar(p["nombre"])
        for p in lista_profesores if p.get("nombre")
    }
    ocupadas_por_prof: Dict[int, List[Tuple[str, str, str]]] = {}
    for a in db.query("SELECT profesor_id, dia, hora_inicio, hora_fin FROM asignaciones_horario"):
        pid = int(a["profesor_id"])
        ini = _normalizar_hhmm(a.get("hora_inicio"))
        fin = _normalizar_hhmm(a.get("hora_fin"))
        dia = _canon_dia(a.get("dia"))
        if dia and ini and fin and _hora(ini) < _hora(fin):
            ocupadas_por_prof.setdefault(pid, []).append((dia, ini, fin))

    disps_por_prof: Dict[int, List[Tuple[str, str, str]]] = {}
    vistos: Dict[int, set] = {}
    for d in db.query("SELECT profesor_id, dia, hora_inicio, hora_fin FROM disponibilidades"):
        pid = int(d["profesor_id"])
        ini = _normalizar_hhmm(d.get("hora_inicio"))
        fin = _normalizar_hhmm(d.get("hora_fin"))
        dia = _canon_dia(d.get("dia"))
        if not (dia and ini and fin and _hora(ini) < _hora(fin)):
            continue
        clave_slot = (db.normalizar(dia), ini, fin)
        conjunto = vistos.setdefault(pid, set())
        if clave_slot in conjunto:
            continue
        conjunto.add(clave_slot)
        disps_por_prof.setdefault(pid, []).append((dia, ini, fin))

    resultado: Dict[str, Dict[str, Any]] = {}
    for pid, clave_prof in prof_clave_por_id.items():
        slots_raw = sorted(
            disps_por_prof.get(pid, []),
            key=lambda s: (_orden_dia(s[0]), _hora(s[1]), _hora(s[2])),
        )
        ocupadas = ocupadas_por_prof.get(pid, [])
        slots_info: List[Dict[str, Any]] = []
        libres = 0
        ocupados = 0
        for dia, ini, fin in slots_raw:
            esta_ocupado = any(
                db.normalizar(od) == db.normalizar(dia) and _franjas_solapan((ini, fin), (oi, of))
                for od, oi, of in ocupadas
            )
            if esta_ocupado:
                ocupados += 1
            else:
                libres += 1
            slots_info.append({
                "dia": dia,
                "hora_inicio": ini,
                "hora_fin": fin,
                "ocupado": esta_ocupado,
            })
        if slots_info:
            resultado[clave_prof] = {
                "slots": slots_info,
                "total": len(slots_info),
                "libres": libres,
                "ocupados": ocupados,
            }
    return resultado


def opciones_carga() -> Dict[str, Any]:
    carreras_rows = db.query("SELECT id, nombre FROM carreras ORDER BY nombre")
    por_id: Dict[int, str] = {}
    nombres_unicos: List[str] = []
    vistos_car = set()
    for c in carreras_rows:
        nom = db.nombre_carrera_canonico(c["nombre"]) or c["nombre"]
        por_id[int(c["id"])] = nom
        k = db._clave_carrera_suave(nom)
        if k not in vistos_car:
            vistos_car.add(k)
            nombres_unicos.append(nom)
    nombres_unicos.sort(key=lambda s: (db.normalizar(s), s))

    info_por_carrera: Dict[str, Dict[str, Dict[str, Any]]] = {
        nombre: {} for nombre in nombres_unicos
    }

    def _registrar(nombre_carrera: Optional[str], nombre_mat: Any, codigo: Any,
                   creditos: Any, semestre: Any, horas_teoria: Any,
                   horas_practica: Any, prioritario: bool) -> None:
        if not nombre_carrera or not nombre_mat:
            return
        nom_limpio = " ".join(str(nombre_mat).strip().split())
        if not nom_limpio:
            return
        cod_limpio = str(codigo or "").strip()
        uc_val = _entero_seguro(creditos)
        ht_val = _entero_seguro(horas_teoria)
        hp_val = _entero_seguro(horas_practica)
        h_total = ht_val + hp_val
        sem_limpio = str(semestre or "").strip()

        destino = info_por_carrera.setdefault(nombre_carrera, {})
        clave = db.normalizar(nom_limpio)
        actual = destino.get(clave)
        if not actual:
            destino[clave] = {
                "nombre": nom_limpio,
                "codigo": cod_limpio,
                "creditos": uc_val,
                "semestre": sem_limpio,
                "horas_teoria": ht_val,
                "horas_practica": hp_val,
                "horas_materia": h_total,
            }
            return
        if cod_limpio and (prioritario or not actual["codigo"]):
            actual["codigo"] = cod_limpio
        if uc_val > 0 and (prioritario or actual["creditos"] <= 0):
            actual["creditos"] = uc_val
        if sem_limpio and (prioritario or not actual["semestre"] or actual["semestre"] == "1er Semestre"):
            actual["semestre"] = sem_limpio
        if h_total > 0 and (prioritario or actual["horas_materia"] <= 0):
            actual["horas_teoria"] = ht_val
            actual["horas_practica"] = hp_val
            actual["horas_materia"] = h_total

    materias_rows = db.query(
        "SELECT carrera_id, nombre, codigo, semestre, unidad_credito FROM materias ORDER BY nombre"
    )
    for m in materias_rows:
        _registrar(
            por_id.get(int(m["carrera_id"])),
            m.get("nombre"),
            m.get("codigo"),
            m.get("unidad_credito"),
            m.get("semestre"),
            0,
            0,
            prioritario=False,
        )

    planes_rows = db.query(
        "SELECT carrera_id, codigo, nombre, unidad_credito, horas_teoria, horas_practica, ciclo "
        "FROM planes_estudio ORDER BY ciclo, codigo, nombre"
    )
    for p in planes_rows:
        _registrar(
            por_id.get(int(p["carrera_id"])),
            p.get("nombre"),
            p.get("codigo"),
            p.get("unidad_credito"),
            p.get("ciclo"),
            p.get("horas_teoria"),
            p.get("horas_practica"),
            prioritario=True,
        )

    materias_por_carrera: Dict[str, List[str]] = {}
    materias_info: Dict[str, Dict[str, Dict[str, Any]]] = {}
    todas_materias: List[str] = []
    vistas_todas = set()

    for nombre_carrera, mapa in info_por_carrera.items():
        nombres_ordenados = sorted(
            (item["nombre"] for item in mapa.values()),
            key=lambda s: (db.normalizar(s), s),
        )
        materias_por_carrera[nombre_carrera] = nombres_ordenados
        materias_info[nombre_carrera] = {
            clave: {
                "codigo": item["codigo"],
                "creditos": item["creditos"],
                "semestre": item["semestre"],
                "horas_teoria": item["horas_teoria"],
                "horas_practica": item["horas_practica"],
                "horas_materia": item["horas_materia"],
            }
            for clave, item in mapa.items()
        }
        for nom in nombres_ordenados:
            cl = db.normalizar(nom)
            if cl not in vistas_todas:
                vistas_todas.add(cl)
                todas_materias.append(nom)

    todas_materias.sort(key=lambda s: (db.normalizar(s), s))

    lista_profesores = profesores()
    disponibilidades_docentes = _disponibilidades_por_profesor(lista_profesores)
    profesores_info: Dict[str, Dict[str, str]] = {}
    for p in lista_profesores:
        clave_p = db.normalizar(p.get("nombre"))
        if not clave_p:
            continue
        profesores_info[clave_p] = {
            "nombre": str(p.get("nombre") or "").strip(),
            "cedula": str(p.get("cedula") or "").strip(),
            "email": str(p.get("email") or "").strip(),
            "condicion": str(p.get("condicion") or "").strip(),
        }

    return {
        "profesores": [p["nombre"] for p in lista_profesores],
        "profesores_info": profesores_info,
        "disponibilidades_docentes": disponibilidades_docentes,
        "franjas": obtener_franjas_sistema(),
        "franjas_defecto": [list(f) for f in FRANJAS_POR_DEFECTO],
        "franjas_personalizadas": bool(db.get_config(CLAVE_CONFIG_FRANJAS, "")),
        "bloqueos_activos": obtener_bloqueos(solo_activos=True),
        "carreras": nombres_unicos,
        "materias": todas_materias,
        "materias_por_carrera": materias_por_carrera,
        "materias_info": materias_info,
        "codigos": [m["codigo"] for m in db.query("SELECT DISTINCT codigo FROM materias WHERE codigo!='' ORDER BY codigo")],
        "ambientes": [s["codigo"] for s in salones()],
    }
