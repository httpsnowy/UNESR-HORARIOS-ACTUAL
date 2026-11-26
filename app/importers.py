"""Importadores de datos: plan de estudio (pensum completo) y oferta académica.

Incluye validación previa en memoria, normalización canónica de carreras para
evitar duplicados y respaldo automático de la base de datos antes de escribir.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import db

ROOT = Path(__file__).resolve().parent.parent

MAPA_PLAN_CARRERA = {
    "ARRHH_2024": "Administración - Administración de Recursos Humanos",
    "ARMF 2024": "Administración - Recursos Materiales y Financieros",
    "AINF_2024": "Administración - Informática",
    "AMER_2024": "Administración - Mercadeo",
    "AOYS_2024": "Administración - Organización y Sistemas",
    "EDMT_2024": "Educación - Docencia en Matemáticas",
    "EDII_2024": "Educación - Docencia en Idioma Inglés",
    "EINI_2024": "Educación Inicial - Sin Mención",
    "EINT_2024": "Educación Integral - Sin Mención",
}


def encontrar_plan_estudio(ruta: Optional[Path] = None) -> Optional[Path]:
    """Busca 'PLAN DE ESTUDIO 2024(1).xlsx' en data/, uploads/ y recursos del paquete."""
    if ruta is not None:
        p = Path(ruta)
        return p if p.exists() else None
    candidatos = [
        db.DATA_DIR / "PLAN DE ESTUDIO 2024(1).xlsx",
        ROOT / "data" / "PLAN DE ESTUDIO 2024(1).xlsx",
        db.RECURSOS / "data" / "PLAN DE ESTUDIO 2024(1).xlsx",
        db.DATA_DIR.parent / "uploads" / "PLAN_DE_ESTUDIO_2024(1).xlsx",
        ROOT / "uploads" / "PLAN_DE_ESTUDIO_2024(1).xlsx",
        db.RECURSOS / "uploads" / "PLAN_DE_ESTUDIO_2024(1).xlsx",
    ]
    for c in candidatos:
        if c.exists():
            return c
    return None


def _facultad(carrera: str) -> str:
    return db.facultad_de_carrera(carrera)


def _resolver_carrera_oferta(carrera_raw: str, mencion_raw: str, hoja: str) -> str:
    carrera = " ".join(str(carrera_raw or "").strip().split())
    mencion = " ".join(str(mencion_raw or "").strip().split())
    if "/" in carrera:
        carrera = carrera.split("/")[0].strip()
    if "/" in mencion:
        mencion = mencion.split("/")[0].strip()

    menc_norm = db.normalizar(mencion)
    carr_norm = db.normalizar(carrera)

    if carrera and mencion and menc_norm not in (carr_norm, "SIN MENCION", "N/A", "NA", "-", "NINGUNA"):
        candidato = f"{carrera} - {mencion}"
    elif carrera:
        candidato = carrera
    elif mencion and menc_norm not in ("SIN MENCION", "N/A", "NA", "-", "NINGUNA"):
        candidato = mencion
    else:
        candidato = MAPA_PLAN_CARRERA.get(str(hoja or "").strip(), str(hoja or "").strip())

    return db.nombre_carrera_canonico(candidato)


def _buscar_col(headers: Sequence[str], *variantes: Tuple[str, ...]) -> Optional[int]:
    for claves in variantes:
        for i, h in enumerate(headers):
            if all(k in h for k in claves):
                return i
    return None


def _leer_hojas_archivo(ruta: Path) -> List[Tuple[str, List[Tuple[Any, ...]]]]:
    ext = ruta.suffix.lower()
    if ext == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        try:
            hojas: List[Tuple[str, List[Tuple[Any, ...]]]] = []
            for ws in wb.worksheets:
                filas = [tuple(r) for r in ws.iter_rows(values_only=True)]
                hojas.append((ws.title, filas))
            return hojas
        finally:
            wb.close()

    if ext in (".csv", ".txt"):
        texto = ruta.read_text(encoding="utf-8-sig", errors="replace")
        lineas = [ln for ln in texto.splitlines() if ln.strip()]
        if not lineas:
            raise ValueError("El archivo de texto está vacío.")
        muestra = "\n".join(lineas[:15])
        delimitador = ","
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
            delimitador = dialecto.delimiter
        except Exception:
            for cand in ("\t", ";", "|", ","):
                if cand in lineas[0]:
                    delimitador = cand
                    break
        lector = csv.reader(lineas, delimiter=delimitador)
        filas = [tuple(row) for row in lector]
        return [(ruta.stem, filas)]

    raise ValueError("Formato no soportado. Use un archivo .xlsx, .csv o .txt.")


def _fusionar_bloques_fijos(
    dia_actual: str, ini_actual: str, fin_actual: str,
    nuevo_dia: str, nuevo_ini: str, nuevo_fin: str,
) -> Tuple[str, str, str, int]:
    pares: List[Tuple[str, str, str]] = []
    if dia_actual and ini_actual and fin_actual:
        ds = [x.strip() for x in str(dia_actual).split("|") if x.strip()]
        is_ = [x.strip() for x in str(ini_actual).split("|") if x.strip()]
        fs = [x.strip() for x in str(fin_actual).split("|") if x.strip()]
        if len(is_) == 1 and len(fs) == 1 and len(ds) > 1:
            is_ = is_ * len(ds)
            fs = fs * len(ds)
        for i in range(min(len(ds), len(is_), len(fs))):
            pares.append((ds[i], is_[i], fs[i]))

    if nuevo_dia and nuevo_ini and nuevo_fin:
        clave_nueva = (db.normalizar(nuevo_dia), nuevo_ini, nuevo_fin)
        if not any((db.normalizar(d), i, f) == clave_nueva for d, i, f in pares):
            pares.append((nuevo_dia, nuevo_ini, nuevo_fin))
    elif nuevo_dia and not pares:
        return nuevo_dia, nuevo_ini, nuevo_fin, 1

    if not pares:
        return "", "", "", 1

    def _ord(d: str) -> int:
        dn = db.normalizar(d)
        for idx, nom in enumerate(db.DIAS_ORDEN):
            if db.normalizar(nom) == dn:
                return idx
        return len(db.DIAS_ORDEN)

    pares.sort(key=lambda x: (_ord(x[0]), x[1], x[2]))
    return (
        "|".join(p[0] for p in pares),
        "|".join(p[1] for p in pares),
        "|".join(p[2] for p in pares),
        len(pares),
    )


def importar_plan_estudio(ruta: Optional[Path] = None) -> Dict[str, int]:
    """Carga o repara el pensum completo desde 'PLAN DE ESTUDIO 2024(1).xlsx'."""
    import openpyxl

    ruta_real = encontrar_plan_estudio(ruta)
    if not ruta_real:
        raise FileNotFoundError("No se encontró el archivo 'PLAN DE ESTUDIO 2024(1).xlsx' en data/ ni uploads/.")

    wb = openpyxl.load_workbook(ruta_real, data_only=True, read_only=True)
    registros_por_hoja: List[Tuple[str, str, List[Tuple]]] = []
    try:
        for ws in wb.worksheets:
            titulo = ws.title.strip()
            nombre_carrera = db.nombre_carrera_canonico(MAPA_PLAN_CARRERA.get(titulo, titulo))
            filas = list(ws.iter_rows(min_row=1, max_col=8, values_only=True))
            cabecera = next(
                (i for i, r in enumerate(filas)
                 if str(r[0] or "").strip().lower() in ("código", "codigo")),
                None,
            )
            items: List[Tuple] = []
            if cabecera is not None:
                ciclo_actual = "INTRODUCTORIO"
                for fila in filas[cabecera + 1:]:
                    codigo = str(fila[0] or "").strip()
                    nombre = " ".join(str(fila[1] or "").strip().split())
                    if not codigo or not nombre:
                        continue
                    if codigo.upper().startswith("CICLO"):
                        ciclo_actual = nombre.upper() if nombre else codigo.upper()
                        continue
                    if len(codigo) > 25 or len(nombre) > 120:
                        continue
                    try:
                        uc = db.normalizar_entero(fila[2], minimo=0, maximo=30, default=0)
                        ht = db.normalizar_entero(fila[3], minimo=0, default=0)
                        hp = db.normalizar_entero(fila[4], minimo=0, default=0)
                    except ValueError:
                        uc = ht = hp = 0
                    opc = str(fila[5] or "").strip()
                    tecnica = str(fila[6] or "").strip()
                    prel = str(fila[7] or "").strip() if len(fila) > 7 and fila[7] else ""
                    items.append((codigo, nombre, uc, ht, hp, ciclo_actual, opc, tecnica, prel))
            registros_por_hoja.append((titulo, nombre_carrera, items))
    finally:
        wb.close()

    total_detectado = sum(len(items) for _, _, items in registros_por_hoja)
    if total_detectado == 0:
        raise ValueError("El archivo de Plan de Estudio no contiene materias válidas para importar.")

    respaldo = db.respaldar_bd("antes_plan_estudio")
    conteos: Dict[str, int] = {}
    total = 0
    try:
        for titulo, nombre_carrera, items in registros_por_hoja:
            car_id = db.get_or_create_carrera_segura(nombre_carrera, permitir_crear=True)
            if car_id is None:
                continue
            n = 0
            for codigo, nombre, uc, ht, hp, ciclo_actual, opc, tecnica, prel in items:
                existe = db.query(
                    "SELECT id FROM planes_estudio WHERE carrera_id=? AND codigo=? AND nombre=? LIMIT 1",
                    (car_id, codigo, nombre),
                )
                if existe:
                    db.execute(
                        """UPDATE planes_estudio SET unidad_credito=?, horas_teoria=?,
                           horas_practica=?, ciclo=?, opcionalidad=?, tecnica=?, prelacion=?
                           WHERE id=?""",
                        (uc, ht, hp, ciclo_actual, opc, tecnica, prel, existe[0]["id"]),
                    )
                else:
                    db.execute(
                        """INSERT INTO planes_estudio
                           (carrera_id,codigo,nombre,unidad_credito,horas_teoria,horas_practica,
                            ciclo,opcionalidad,tecnica,prelacion)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (car_id, codigo, nombre, uc, ht, hp, ciclo_actual, opc, tecnica, prel),
                    )
                db.get_or_create_materia(nombre, car_id, codigo, ciclo_actual, uc)
                n += 1
            conteos[titulo] = n
            total += n
    except Exception:
        db.restaurar_bd(respaldo)
        raise

    return {"total": total, **conteos}


def importar_oferta_excel(ruta: Path) -> Dict[str, Any]:
    """Valida e importa la oferta académica (.xlsx, .csv o .txt) sin dañar la BD."""
    if not ruta.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {ruta}")

    hojas = _leer_hojas_archivo(ruta)
    if not hojas:
        raise ValueError("El archivo no contiene hojas ni filas.")

    parece_plan = any(titulo.strip() in MAPA_PLAN_CARRERA for titulo, _ in hojas)

    carreras_existentes = db.query("SELECT id, nombre FROM carreras")
    tiene_catalogo_carreras = bool(carreras_existentes)

    registros: List[Dict[str, Any]] = []
    advertencias: List[str] = []
    hojas_con_cabecera = 0

    for titulo_hoja, filas in hojas:
        cab = next(
            (i for i, r in enumerate(filas)
             if any(
                 ("NOMBRES" in db.normalizar(c) and "APELLIDOS" in db.normalizar(c))
                 or db.normalizar(c) in ("DOCENTE", "PROFESOR", "FACILITADOR")
                 for c in r
             )),
            None,
        )
        if cab is None:
            continue
        hojas_con_cabecera += 1
        headers = [db.normalizar(c) for c in filas[cab]]

        i_prof = _buscar_col(headers, ("NOMBRES", "APELLIDOS"), ("DOCENTE",), ("PROFESOR",), ("FACILITADOR",))
        i_cod = _buscar_col(headers, ("CODIGO",))
        i_mat = _buscar_col(headers, ("NOMBRE", "CURSO"), ("MATERIA",), ("UNIDAD", "CURRICULAR"), ("ASIGNATURA",), ("CURSO",))
        i_carr = _buscar_col(headers, ("CARRERA",), ("PNF",))
        i_menc = _buscar_col(headers, ("MENCION",))
        i_sec = _buscar_col(headers, ("SECCION",))
        i_dia = _buscar_col(headers, ("DIA",))
        i_hora = _buscar_col(headers, ("HORARIO",), ("HORA",))
        i_amb = _buscar_col(headers, ("AMBIENTE",), ("AULA",), ("SALON",))
        i_uc = _buscar_col(headers, ("UNIDAD", "CREDITO"), ("CREDITO",), ("U.C",), ("UC",))
        i_comp = _buscar_col(headers, ("COMPARTID",))

        if i_prof is None or i_mat is None:
            advertencias.append(f"Hoja «{titulo_hoja}»: faltan columnas de Docente o Materia; omitida.")
            continue

        for num_fila, fila in enumerate(filas[cab + 1:], start=cab + 2):
            def val(idx: Optional[int]) -> str:
                if idx is None or idx >= len(fila) or fila[idx] is None:
                    return ""
                return " ".join(str(fila[idx]).strip().split())

            profesor = val(i_prof)
            materia = val(i_mat)
            if not profesor or not materia:
                continue
            prof_n = db.normalizar(profesor)
            mat_n = db.normalizar(materia)
            if prof_n.startswith("TOTAL") or "NOMBRES Y APELLIDOS" in prof_n or mat_n in ("MATERIA", "CURSO", "NOMBRE DEL CURSO"):
                continue

            nombre_carrera = _resolver_carrera_oferta(val(i_carr), val(i_menc), titulo_hoja)
            if not nombre_carrera:
                advertencias.append(f"{titulo_hoja} fila {num_fila}: sin carrera identificable; omitida.")
                continue

            carrera_existente = db.buscar_carrera_existente(nombre_carrera)
            es_oficial = nombre_carrera in db.CARRERAS_CANONICAS
            if tiene_catalogo_carreras and carrera_existente is None and not es_oficial:
                advertencias.append(
                    f"{titulo_hoja} fila {num_fila}: carrera «{nombre_carrera}» no coincide con "
                    f"ninguna carrera registrada; fila omitida para evitar duplicados."
                )
                continue

            try:
                creditos = db.normalizar_entero(val(i_uc), minimo=0, maximo=30, default=0)
            except ValueError:
                creditos = 0

            dia_raw = val(i_dia)
            dia = next((d for d in db.DIAS_ORDEN if db.normalizar(d) == db.normalizar(dia_raw)), dia_raw)
            inicio, fin = _parsear_hora(val(i_hora))
            if inicio and fin and inicio >= fin:
                inicio, fin = "", ""

            amb_raw = val(i_amb).upper()
            amb_limpio = amb_raw if (not amb_raw or amb_raw in db.AMBIENTES_OFICIALES) else ""

            registros.append({
                "hoja": titulo_hoja,
                "profesor": profesor,
                "carrera": carrera_existente["nombre"] if carrera_existente else nombre_carrera,
                "materia": materia,
                "codigo": val(i_cod),
                "creditos": creditos,
                "seccion": val(i_sec) or "Sección A",
                "dia": dia,
                "inicio": inicio,
                "fin": fin,
                "ambiente": amb_limpio,
                "compartidos": val(i_comp),
            })

    if hojas_con_cabecera == 0:
        if parece_plan:
            raise ValueError(
                "Este archivo corresponde al Plan de Estudio (pensum), no a una Oferta Académica. "
                "Use la opción «Cargar plan de estudio» en el menú lateral."
            )
        raise ValueError(
            "No se encontraron columnas válidas de Oferta Académica "
            "(se requieren al menos columnas de Docente/Nombres y Apellidos y Materia/Nombre del Curso). "
            "No se realizó ningún cambio en la base de datos."
        )

    if not registros:
        detalle = (" " + advertencias[0]) if advertencias else ""
        raise ValueError(
            "El archivo no contiene filas válidas para importar." + detalle +
            " No se realizó ningún cambio en la base de datos."
        )

    respaldo = db.respaldar_bd("antes_importar_oferta")
    insertados = 0
    errores: List[str] = []

    try:
        for reg in registros:
            try:
                car_id = db.get_or_create_carrera_segura(reg["carrera"], permitir_crear=True)
                if car_id is None:
                    continue
                prof_id = db.get_or_create("profesores", "nombre", reg["profesor"].upper())
                mat_id = db.get_or_create_materia(
                    reg["materia"], car_id, reg["codigo"], "OFERTA 2026-2", reg["creditos"]
                )
                exists = db.query(
                    "SELECT id, dia_fijo, hora_inicio_fija, hora_fin_fija, salon_preferido, compartidos "
                    "FROM carga_academica WHERE profesor_id=? AND materia_id=? AND seccion=? LIMIT 1",
                    (prof_id, mat_id, reg["seccion"]),
                )
                if exists:
                    ex = exists[0]
                    cid = int(ex["id"])
                    d_f, i_f, f_f, n_bloq = _fusionar_bloques_fijos(
                        ex.get("dia_fijo", ""),
                        ex.get("hora_inicio_fija", ""),
                        ex.get("hora_fin_fija", ""),
                        reg["dia"],
                        reg["inicio"],
                        reg["fin"],
                    )
                    amb_final = reg["ambiente"] or (ex.get("salon_preferido") or "")
                    comp_final = reg["compartidos"] or (ex.get("compartidos") or "")
                    db.execute(
                        """UPDATE carga_academica SET bloques_semanales=?, dia_fijo=?,
                           hora_inicio_fija=?, hora_fin_fija=?, salon_preferido=?, compartidos=?
                           WHERE id=?""",
                        (n_bloq, d_f, i_f, f_f, amb_final, comp_final, cid),
                    )
                else:
                    db.execute(
                        """INSERT INTO carga_academica
                           (profesor_id,materia_id,seccion,bloques_semanales,salon_preferido,
                            dia_fijo,hora_inicio_fija,hora_fin_fija,compartidos)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (prof_id, mat_id, reg["seccion"], 1, reg["ambiente"],
                         reg["dia"], reg["inicio"], reg["fin"], reg["compartidos"]),
                    )

                if reg["dia"] and reg["inicio"] and reg["fin"]:
                    disp = db.query(
                        """SELECT id FROM disponibilidades WHERE profesor_id=? AND dia=?
                           AND hora_inicio=? AND hora_fin=? LIMIT 1""",
                        (prof_id, reg["dia"], reg["inicio"], reg["fin"]),
                    )
                    if not disp:
                        db.execute(
                            """INSERT INTO disponibilidades (profesor_id,dia,hora_inicio,hora_fin)
                               VALUES (?,?,?,?)""",
                            (prof_id, reg["dia"], reg["inicio"], reg["fin"]),
                        )
                insertados += 1
            except Exception as exc:
                errores.append(f"{reg['hoja']}: {exc}")

        if insertados == 0:
            db.restaurar_bd(respaldo)
            raise ValueError("No se pudo guardar ninguna fila válida; se restauró la base de datos.")
    except Exception:
        db.restaurar_bd(respaldo)
        raise

    return {
        "insertados": insertados,
        "omitidos": len(advertencias),
        "advertencias": advertencias[:15],
        "errores": errores[:20],
        "respaldo": str(respaldo.name) if respaldo else "",
    }


def _parsear_hora(texto: str):
    m = re.search(r"(\d{1,2}:\d{2})\s*(?:a|-|–|—|a las)\s*(\d{1,2}:\d{2})", str(texto or ""), re.I)
    if not m:
        return "", ""

    def norm_h(t: str) -> str:
        h, mi = t.split(":")
        hi, mii = int(h), int(mi)
        if not (0 <= hi <= 23 and 0 <= mii <= 59):
            return ""
        return f"{hi:02d}:{mii:02d}"

    return norm_h(m.group(1)), norm_h(m.group(2))
