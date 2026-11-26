"""Capa de acceso a datos unificada (SQLite + Supabase) con protección contra duplicados, respaldos y configuración persistente."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

EMPACETADO = getattr(sys, "frozen", False)
RECURSOS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ROOT = RECURSOS if EMPACETADO else Path(__file__).resolve().parent.parent

if EMPACETADO:
    base_escritura = Path(sys.executable).resolve().parent
    if os.name == "nt":
        base_escritura = Path(os.environ.get("APPDATA", base_escritura)) / "UNESR_Horarios"
    else:
        base_escritura = Path(os.path.expanduser("~/.local/share/UNESR_Horarios"))
    base_escritura.mkdir(parents=True, exist_ok=True)
    DATA_DIR = base_escritura / "data"
else:
    DATA_DIR = ROOT / "data"

DB_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "universidad_horarios.db"))
if not DB_PATH.is_absolute():
    DB_PATH = (base_escritura if EMPACETADO else ROOT) / DB_PATH

DIAS_ORDEN = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
FRANJAS = [
    ("07:00", "07:45"), ("07:45", "08:30"), ("08:30", "09:15"),
    ("09:20", "10:05"), ("10:05", "10:50"), ("10:50", "11:35"),
    ("11:35", "12:15"), ("12:30", "13:15"), ("13:15", "14:00"),
    ("14:10", "14:55"), ("14:55", "15:35"), ("15:40", "16:25"),
    ("16:25", "17:10"), ("17:10", "18:00"), ("18:00", "18:45"),
]
CAPACIDAD_DEFECTO = 45
AMBIENTES_OFICIALES: Tuple[str, ...] = tuple(
    [f"P1-{n:02d}" for n in range(1, 9)]
    + [f"P2-{n:02d}" for n in range(9, 23)]
    + [f"P3-{n:02d}" for n in range(23, 28)]
    + [f"P4-{n:02d}" for n in range(28, 38)]
    + ["SATELITAL-01", "SATELITAL-02", "VIRTUAL-01", "VIRTUAL-02"]
)
AMBIENTES_ESPECIALES = ["SATELITAL-01", "SATELITAL-02", "VIRTUAL-01", "VIRTUAL-02"]

CARRERAS_CANONICAS: Tuple[str, ...] = (
    "Administración - Administración de Recursos Humanos",
    "Administración - Recursos Materiales y Financieros",
    "Administración - Informática",
    "Administración - Mercadeo",
    "Administración - Organización y Sistemas",
    "Educación - Docencia en Matemáticas",
    "Educación - Docencia en Idioma Inglés",
    "Educación Inicial - Sin Mención",
    "Educación Integral - Sin Mención",
    "PNF Fisioterapia",
    "PNF Veterinaria",
    "PNF Agroecología",
)

_ALIAS_CARRERAS_RAW: Dict[str, str] = {
    "ARRHH_2024": "Administración - Administración de Recursos Humanos",
    "ARRHH 2024": "Administración - Administración de Recursos Humanos",
    "ARRHH": "Administración - Administración de Recursos Humanos",
    "ARMF 2024": "Administración - Recursos Materiales y Financieros",
    "ARMF_2024": "Administración - Recursos Materiales y Financieros",
    "ARMF": "Administración - Recursos Materiales y Financieros",
    "AINF_2024": "Administración - Informática",
    "AINF 2024": "Administración - Informática",
    "AINF": "Administración - Informática",
    "AMER_2024": "Administración - Mercadeo",
    "AMER 2024": "Administración - Mercadeo",
    "AMER": "Administración - Mercadeo",
    "AOYS_2024": "Administración - Organización y Sistemas",
    "AOYS 2024": "Administración - Organización y Sistemas",
    "AOYS": "Administración - Organización y Sistemas",
    "EDMT_2024": "Educación - Docencia en Matemáticas",
    "EDMT 2024": "Educación - Docencia en Matemáticas",
    "EDMT": "Educación - Docencia en Matemáticas",
    "EDII_2024": "Educación - Docencia en Idioma Inglés",
    "EDII 2024": "Educación - Docencia en Idioma Inglés",
    "EDII": "Educación - Docencia en Idioma Inglés",
    "EINI_2024": "Educación Inicial - Sin Mención",
    "EINI 2024": "Educación Inicial - Sin Mención",
    "EINI": "Educación Inicial - Sin Mención",
    "EINT_2024": "Educación Integral - Sin Mención",
    "EINT 2024": "Educación Integral - Sin Mención",
    "EINT": "Educación Integral - Sin Mención",
    "ADMINISTRACION - RECURSOS HUMANOS": "Administración - Administración de Recursos Humanos",
    "ADMINISTRACION MENCION RECURSOS HUMANOS": "Administración - Administración de Recursos Humanos",
    "ADMINISTRACION MENCION ADMINISTRACION DE RECURSOS HUMANOS": "Administración - Administración de Recursos Humanos",
    "ADMINISTRACION DE RECURSOS HUMANOS": "Administración - Administración de Recursos Humanos",
    "RECURSOS HUMANOS": "Administración - Administración de Recursos Humanos",
    "RRHH": "Administración - Administración de Recursos Humanos",
    "R.R.H.H.": "Administración - Administración de Recursos Humanos",
    "ADMINISTRACION MENCION RECURSOS MATERIALES Y FINANCIEROS": "Administración - Recursos Materiales y Financieros",
    "RECURSOS MATERIALES Y FINANCIEROS": "Administración - Recursos Materiales y Financieros",
    "RMF": "Administración - Recursos Materiales y Financieros",
    "R.M.F.": "Administración - Recursos Materiales y Financieros",
    "ADMINISTRACION MENCION INFORMATICA": "Administración - Informática",
    "INFORMATICA": "Administración - Informática",
    "ADMINISTRACION MENCION MERCADEO": "Administración - Mercadeo",
    "MERCADEO": "Administración - Mercadeo",
    "ADMINISTRACION MENCION ORGANIZACION Y SISTEMAS": "Administración - Organización y Sistemas",
    "ORGANIZACION Y SISTEMAS": "Administración - Organización y Sistemas",
    "OYS": "Administración - Organización y Sistemas",
    "O Y S": "Administración - Organización y Sistemas",
    "EDUCACION - DOCENCIA EN MATEMATICA": "Educación - Docencia en Matemáticas",
    "EDUCACION - MATEMATICAS": "Educación - Docencia en Matemáticas",
    "EDUCACION - MATEMATICA": "Educación - Docencia en Matemáticas",
    "EDUCACION MENCION DOCENCIA EN MATEMATICAS": "Educación - Docencia en Matemáticas",
    "EDUCACION MENCION DOCENCIA EN MATEMATICA": "Educación - Docencia en Matemáticas",
    "EDUCACION MENCION MATEMATICAS": "Educación - Docencia en Matemáticas",
    "EDUCACION MENCION MATEMATICA": "Educación - Docencia en Matemáticas",
    "DOCENCIA EN MATEMATICAS": "Educación - Docencia en Matemáticas",
    "DOCENCIA EN MATEMATICA": "Educación - Docencia en Matemáticas",
    "MATEMATICAS": "Educación - Docencia en Matemáticas",
    "MATEMATICA": "Educación - Docencia en Matemáticas",
    "EDUCACION - INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION - IDIOMA INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION - DOCENCIA EN INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION MENCION DOCENCIA EN IDIOMA INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION MENCION DOCENCIA EN INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION MENCION IDIOMA INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION MENCION INGLES": "Educación - Docencia en Idioma Inglés",
    "DOCENCIA EN IDIOMA INGLES": "Educación - Docencia en Idioma Inglés",
    "DOCENCIA EN INGLES": "Educación - Docencia en Idioma Inglés",
    "IDIOMA INGLES": "Educación - Docencia en Idioma Inglés",
    "INGLES": "Educación - Docencia en Idioma Inglés",
    "EDUCACION INICIAL": "Educación Inicial - Sin Mención",
    "EDUCACION - INICIAL": "Educación Inicial - Sin Mención",
    "EDUCACION - EDUCACION INICIAL": "Educación Inicial - Sin Mención",
    "EDUCACION MENCION INICIAL": "Educación Inicial - Sin Mención",
    "EDUCACION MENCION EDUCACION INICIAL": "Educación Inicial - Sin Mención",
    "INICIAL": "Educación Inicial - Sin Mención",
    "EDUCACION INTEGRAL": "Educación Integral - Sin Mención",
    "EDUCACION - INTEGRAL": "Educación Integral - Sin Mención",
    "EDUCACION - EDUCACION INTEGRAL": "Educación Integral - Sin Mención",
    "EDUCACION MENCION INTEGRAL": "Educación Integral - Sin Mención",
    "EDUCACION MENCION EDUCACION INTEGRAL": "Educación Integral - Sin Mención",
    "INTEGRAL": "Educación Integral - Sin Mención",
    "PNF EN FISIOTERAPIA": "PNF Fisioterapia",
    "FISIOTERAPIA": "PNF Fisioterapia",
    "PNF EN MEDICINA VETERINARIA": "PNF Veterinaria",
    "PNF MEDICINA VETERINARIA": "PNF Veterinaria",
    "MEDICINA VETERINARIA": "PNF Veterinaria",
    "VETERINARIA": "PNF Veterinaria",
    "PNF EN AGROECOLOGIA": "PNF Agroecología",
    "AGROECOLOGIA": "PNF Agroecología",
}

_local = threading.local()


def _env() -> Dict[str, str]:
    rutas = [ROOT / ".env"]
    if EMPACETADO:
        rutas += [Path(sys.executable).resolve().parent / ".env",
                  base_escritura / ".env"]
    result: Dict[str, str] = {}
    for path in rutas:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def configuracion() -> Dict[str, str]:
    cfg = _env()
    for key in ("SUPABASE_URL", "SUPABASE_KEY", "DB_BACKEND", "DATABASE_PATH", "FLASK_SECRET_KEY"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def backend_activo() -> str:
    cfg = configuracion()
    mode = cfg.get("DB_BACKEND", "auto").lower()
    if mode == "sqlite":
        return "sqlite"
    if cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_KEY"):
        return "supabase" if mode in ("auto", "supabase") else "sqlite"
    return "sqlite"


class DatabaseError(RuntimeError):
    pass


# ─────────────────────────── SQLite ───────────────────────────

def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _sqlite_query(sql: str, params: Sequence = ()) -> List[Dict]:
    conn = _sqlite_conn()
    try:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def _sqlite_execute(sql: str, params: Sequence = ()) -> int:
    conn = _sqlite_conn()
    try:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.lastrowid if cur.lastrowid is not None else cur.rowcount
    finally:
        conn.close()


def _sqlite_executescript(sql: str) -> None:
    conn = _sqlite_conn()
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


# ──────────────────── Respaldos e integridad (SQLite) ────────────────────

def respaldar_bd(etiqueta: str = "auto", max_copias: int = 15) -> Optional[Path]:
    if backend_activo() != "sqlite" or not DB_PATH.exists():
        return None
    carpeta = DB_PATH.parent / "backups"
    carpeta.mkdir(parents=True, exist_ok=True)
    etq = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(etiqueta or "auto")).strip("_") or "auto"
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
    destino = carpeta / f"{DB_PATH.stem}_{etq}_{marca}.db"
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(destino, timeout=30)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    try:
        copias = sorted(
            carpeta.glob(f"{DB_PATH.stem}_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for vieja in copias[max_copias:]:
            vieja.unlink(missing_ok=True)
    except Exception:
        pass
    return destino


def restaurar_bd(ruta_backup: Optional[Path]) -> bool:
    if backend_activo() != "sqlite" or not ruta_backup or not Path(ruta_backup).exists():
        return False
    src = sqlite3.connect(ruta_backup, timeout=30)
    dst = sqlite3.connect(DB_PATH, timeout=30)
    try:
        src.backup(dst)
        dst.commit()
        return True
    finally:
        dst.close()
        src.close()


def verificar_integridad() -> Tuple[bool, str]:
    if backend_activo() != "sqlite" or not DB_PATH.exists():
        return True, "ok"
    conn = _sqlite_conn()
    try:
        fila = conn.execute("PRAGMA integrity_check").fetchone()
        res = str(fila[0]) if fila else "error"
        return res.lower() == "ok", res
    finally:
        conn.close()


# ─────────────────────────── Supabase / PostgREST ───────────────────────────

def _rest(sql_or_table: str, method: str = "GET", params: Optional[Dict] = None,
          body: Optional[Any] = None, extra_headers: Optional[Dict] = None,
          return_headers: bool = False) -> Any:
    import httpx

    cfg = configuracion()
    url = cfg.get("SUPABASE_URL", "").rstrip("/")
    key = cfg.get("SUPABASE_KEY", "")
    if not url or not key:
        raise DatabaseError("Faltan SUPABASE_URL/SUPABASE_KEY en .env")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if extra_headers:
        headers.update(extra_headers)
    endpoint = f"{url}/rest/v1/{sql_or_table}"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(method, endpoint, headers=headers, params=params, json=body)
            if resp.status_code >= 400:
                raise DatabaseError(f"Supabase {resp.status_code}: {resp.text[:400]}")
            datos = resp.json() if resp.content else None
            return (datos, dict(resp.headers)) if return_headers else datos
    except DatabaseError:
        raise
    except Exception as exc:  # pragma: no cover - red
        raise DatabaseError(f"No se pudo conectar con Supabase: {exc}") from exc


def _rest_all_rows(tabla: str) -> List[Dict]:
    salida: List[Dict] = []
    inicio = 0
    paso = 1000
    while True:
        lote = _rest(
            tabla,
            "GET",
            {"select": "*"},
            extra_headers={"Range": f"{inicio}-{inicio + paso - 1}"},
        ) or []
        if not lote:
            break
        salida.extend(lote)
        if len(lote) < paso:
            break
        inicio += paso
    return salida


def _parse_where(sql: str) -> Tuple[str, List[Tuple[str, str, Any]]]:
    text = " ".join(sql.split())
    where: List[Tuple[str, str, Any]] = []
    if " WHERE " in text:
        text, rest = text.split(" WHERE ", 1)
        rest = rest.split(" ORDER BY ")[0].split(" LIMIT ")[0]
        for part in rest.split(" AND "):
            part = part.strip()
            if " != ?" in part:
                col = part.split("!=")[0].strip()
                where.append((col, "neq", None))
            elif " IS NOT NULL" in part.upper():
                where.append((part.upper().replace(" IS NOT NULL", ""), "not.is", None))
            elif " LIKE ?" in part.upper():
                where.append((part.upper().replace(" LIKE ?", ""), "like", None))
            elif " = ?" in part:
                where.append((part.split("=")[0].strip(), "eq", None))
    return text, where


def _table_from_select(sql: str) -> str:
    text = " ".join(sql.split())
    after = text.split(" FROM ", 1)[1] if " FROM " in text else text.split("FROM", 1)[-1]
    return after.strip().split()[0].strip('"')


# ─────────────────────────── API pública ───────────────────────────

_mem_cache: Dict[str, Any] = {"at": 0.0, "conn": None}
TABLAS_REMOTAS = ["facultades", "carreras", "salones", "profesores",
                  "disponibilidades", "planes_estudio", "materias",
                  "carga_academica", "asignaciones_horario", "configuracion"]


def _supabase_mem_conn() -> sqlite3.Connection:
    import time

    ahora = time.monotonic()
    if _mem_cache["conn"] is not None and ahora - _mem_cache["at"] < 5.0:
        return _mem_cache["conn"]

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for tabla in TABLAS_REMOTAS:
        try:
            filas = _rest_all_rows(tabla)
        except DatabaseError:
            continue
        if not filas:
            continue
        cols = list(filas[0].keys())
        tipos = {}
        for col in cols:
            for f in filas:
                v = f.get(col)
                if v is None:
                    continue
                tipos[col] = "INTEGER" if isinstance(v, (int, bool)) else "REAL" if isinstance(v, float) else "TEXT"
                break
            else:
                tipos[col] = "TEXT"
        ddl = ", ".join(f'"{c}" {tipos[c]}' for c in cols)
        conn.execute(f'CREATE TABLE "{tabla}" ({ddl})')
        marcadores = ",".join("?" for _ in cols)
        conn.executemany(
            f'INSERT INTO "{tabla}" ({",".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({marcadores})',
            [tuple(f.get(c) for c in cols) for f in filas],
        )
    conn.commit()
    _mem_cache.update(at=ahora, conn=conn)
    return conn


def query(sql: str, params: Sequence = ()) -> List[Dict[str, Any]]:
    if backend_activo() == "sqlite":
        return _sqlite_query(sql, params)
    try:
        return _rest_query(sql, params)
    except DatabaseError:
        conn = _supabase_mem_conn()
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def _rest_query(sql: str, params: Sequence) -> List[Dict]:
    text = " ".join(sql.split())
    if not re.match(r"^SELECT\s", text, re.I) or " FROM " not in text:
        raise DatabaseError(f"SELECT no traducible a PostgREST: {sql[:120]}")

    selects = text.split(" FROM ", 1)[0][6:].strip()
    table = _table_from_select(text)

    mcount = re.fullmatch(r"COUNT\s*\(\s*\*\s*\)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?",
                          selects, re.I)
    if mcount:
        if " JOIN " in text or " WHERE " in text:
            raise DatabaseError("COUNT(*) con JOIN/WHERE -> caché SQLite")
        alias = mcount.group(1) or "n"
        _, hdrs = _rest(table, "GET", {"select": "id", "limit": 1},
                        extra_headers={"Prefer": "count=exact"}, return_headers=True)
        total = 0
        rango = hdrs.get("content-range", "")
        if "/" in rango:
            try:
                total = int(rango.rsplit("/", 1)[1])
            except ValueError:
                pass
        return [{alias: total}]

    cols: List[str] = []
    alias_map: Dict[str, str] = {}
    distinct = False
    items = ["*"] if selects == "*" else [c.strip() for c in selects.split(",")]
    for item in items:
        m = re.fullmatch(r"DISTINCT\s+([A-Za-z_]\w*)", item, re.I)
        if m:
            distinct = True
            cols.append(m.group(1))
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*)\s+AS\s+([A-Za-z_]\w*)", item, re.I)
        if m:
            cols.append(m.group(1))
            alias_map[m.group(2)] = m.group(1)
            continue
        if re.fullmatch(r"[A-Za-z_]\w*", item):
            cols.append(item)
            continue
        raise DatabaseError(f"SELECT no traducible a PostgREST: {item}")

    params_list = list(params)
    filters: List[str] = []
    cond = ""
    if " WHERE " in text:
        cond = text.split(" WHERE ", 1)[1].split(" ORDER BY ")[0].split(" LIMIT ")[0]
    op_map = {"=": "eq", "!=": "neq", "<>": "neq", ">": "gt", "<": "lt", ">=": "gte", "<=": "lte"}
    for raw in ([c.strip() for c in cond.split(" AND ")] if cond.strip() else []):
        if not raw:
            continue
        m = re.fullmatch(r"(\w+)\s*(>=|<=|!=|<>|=|>|<)\s*\?", raw)
        if m and params_list:
            filters.append(f"{m.group(1)}={op_map[m.group(2)]}.{_rest_val(params_list.pop(0))}")
            continue
        m = re.fullmatch(r"(\w+)\s+IN\s*\(\s*(\?(?:\s*,\s*\?)*)\s*\)", raw, re.I)
        if m and params_list and raw.count("?") <= len(params_list):
            n = raw.count("?")
            vals = params_list[:n]
            del params_list[:n]
            filters.append(f"{m.group(1)}=in.({','.join(_rest_val(v) for v in vals)})")
            continue
        m = re.fullmatch(r"(\w+)\s+IS\s+NOT\s+NULL", raw, re.I)
        if m:
            filters.append(f"{m.group(1)}=not.is.null")
            continue
        m = re.fullmatch(r"(\w+)\s*(!=|<>|=)\s*'([^']*)'", raw)
        if m:
            filters.append(f"{m.group(1)}={op_map[m.group(2)]}.{m.group(3)}")
            continue
        m = re.fullmatch(r"(\w+)\s+LIKE\s+'([^']*)'", raw, re.I)
        if m:
            filters.append(f"{m.group(1)}=like.{m.group(2)}")
            continue
        raise DatabaseError(f"WHERE no traducible a PostgREST: {raw}")

    if params_list:
        raise DatabaseError("Parámetros WHERE sin consumir -> caché SQLite")

    q: Dict[str, Any] = {"select": ",".join(cols)}
    for f in filters:
        key, val = f.split("=", 1)
        if key in q:
            q[key] = q[key] + "," + val
        else:
            q[key] = val

    if " ORDER BY " in text:
        orden: List[str] = []
        for parte in text.split(" ORDER BY ", 1)[1].split(" LIMIT ")[0].split(","):
            m = re.fullmatch(r"\s*([A-Za-z_]\w*)(?:\s+(ASC|DESC))?\s*", parte, re.I)
            if not m:
                raise DatabaseError(f"ORDER BY no traducible a PostgREST: {parte}")
            orden.append(f"{m.group(1)}.{(m.group(2) or 'ASC').lower()}")
        q["order"] = ",".join(orden)
    if " LIMIT " in text:
        lim = text.split(" LIMIT ", 1)[1].split()[0]
        if not lim.isdigit():
            raise DatabaseError(f"LIMIT no traducible a PostgREST: {lim}")
        q["limit"] = int(lim)

    filas = _rest(table, "GET", q) or []
    if distinct and cols != ["*"]:
        vistos: set = set()
        unicas: List[Dict] = []
        for fila in filas:
            clave = tuple(str(fila.get(c)) for c in cols)
            if clave not in vistos:
                vistos.add(clave)
                unicas.append(fila)
        filas = unicas
    for alias, original in alias_map.items():
        for fila in filas:
            if alias not in fila and original in fila:
                fila[alias] = fila[original] if original in cols else fila.pop(original)
    return filas


def _rest_val(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _invalidar_cache() -> None:
    _mem_cache.update(at=0.0, conn=None)


def execute(sql: str, params: Sequence = ()) -> int:
    if backend_activo() == "sqlite":
        return _sqlite_execute(sql, params)
    resultado = _rest_write(sql, params)
    _invalidar_cache()
    if isinstance(resultado, list) and resultado and isinstance(resultado[0], dict):
        if "id" in resultado[0]:
            return int(resultado[0]["id"])
    return 1


def _rest_write(sql: str, params: Sequence) -> Any:
    text = " ".join(sql.split())
    vals = list(params)
    m = re.match(r"INSERT INTO (\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)", text, re.I)
    if m:
        table, cols = m.group(1), [c.strip() for c in m.group(2).split(",")]
        row = dict(zip(cols, vals))
        return _rest(table, "POST", body=row)
    m = re.match(r"UPDATE (\w+) SET (.+?) WHERE (\w+)\s*=\s*\?", text, re.I)
    if m:
        table, sets, key = m.group(1), m.group(2), m.group(3)
        assignments = {}
        for item in sets.split(","):
            c, _, v = item.partition("=")
            assignments[c.strip()] = vals.pop(0) if vals else None
        pk = vals.pop(0) if vals else None
        assignments.pop("id", None)
        return _rest(table, "PATCH", {key: f"eq.{_rest_val(pk)}"}, assignments)
    m = re.match(r"DELETE FROM (\w+) WHERE (\w+)\s*=\s*\?", text, re.I)
    if m:
        return _rest(m.group(1), "DELETE", {m.group(2): f"eq.{_rest_val(vals[0])}"})
    raise DatabaseError(f"SQL no soportado por el adaptador Supabase: {sql[:120]}")


def borrar_donde(tabla: str, campo: str, valor: Any) -> None:
    if backend_activo() == "sqlite":
        execute(f"DELETE FROM {tabla} WHERE {campo} = ?", (valor,))
    else:
        _rest(tabla, "DELETE", {campo: f"eq.{_rest_val(valor)}"})
        _invalidar_cache()


def borrar_donde_neq(tabla: str, campo: str, valor: Any) -> None:
    if backend_activo() == "sqlite":
        execute(f"DELETE FROM {tabla} WHERE {campo} != ?", (valor,))
    else:
        _rest(tabla, "DELETE", {campo: f"neq.{_rest_val(valor)}"})
        _invalidar_cache()


def exec_many(sql: str, seq: Iterable[Sequence]) -> None:
    if backend_activo() == "sqlite":
        conn = _sqlite_conn()
        try:
            conn.executemany(sql, [tuple(x) for x in seq])
            conn.commit()
        finally:
            conn.close()
        return
    for params in seq:
        execute(sql, params)


def init_db() -> None:
    if backend_activo() != "sqlite":
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        semilla = RECURSOS / "data" / DB_PATH.name
        if semilla.exists():
            shutil.copy2(semilla, DB_PATH)
    _sqlite_executescript("""
    CREATE TABLE IF NOT EXISTS facultades (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS carreras (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
        facultad_id INTEGER NOT NULL, codigo TEXT DEFAULT '', UNIQUE(nombre, facultad_id),
        FOREIGN KEY(facultad_id) REFERENCES facultades(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS salones (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
        capacidad INTEGER DEFAULT 40, edificio TEXT DEFAULT 'Edificio Principal', es_camillas INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS profesores (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE,
        cedula TEXT DEFAULT '', email TEXT DEFAULT '', condicion TEXT DEFAULT 'Contratado/a', mencion TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS disponibilidades (id INTEGER PRIMARY KEY AUTOINCREMENT,
        profesor_id INTEGER NOT NULL, dia TEXT NOT NULL, hora_inicio TEXT NOT NULL, hora_fin TEXT NOT NULL,
        UNIQUE(profesor_id,dia,hora_inicio,hora_fin), FOREIGN KEY(profesor_id) REFERENCES profesores(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS planes_estudio (id INTEGER PRIMARY KEY AUTOINCREMENT, carrera_id INTEGER NOT NULL,
        codigo TEXT DEFAULT '', nombre TEXT NOT NULL, unidad_credito INTEGER DEFAULT 0,
        horas_teoria INTEGER DEFAULT 0, horas_practica INTEGER DEFAULT 0, ciclo TEXT DEFAULT '',
        opcionalidad TEXT DEFAULT '', tecnica TEXT DEFAULT '', prelacion TEXT DEFAULT '',
        UNIQUE(carrera_id,codigo,nombre), FOREIGN KEY(carrera_id) REFERENCES carreras(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS materias (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
        codigo TEXT DEFAULT '', carrera_id INTEGER NOT NULL, semestre TEXT DEFAULT '1er Semestre',
        unidad_credito INTEGER DEFAULT 0, mencion TEXT DEFAULT '', UNIQUE(nombre,carrera_id),
        FOREIGN KEY(carrera_id) REFERENCES carreras(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS carga_academica (id INTEGER PRIMARY KEY AUTOINCREMENT,
        profesor_id INTEGER NOT NULL, materia_id INTEGER NOT NULL, seccion TEXT DEFAULT 'Sección A',
        bloques_semanales INTEGER DEFAULT 1, salon_preferido TEXT DEFAULT '', dia_fijo TEXT DEFAULT '',
        hora_inicio_fija TEXT DEFAULT '', hora_fin_fija TEXT DEFAULT '', compartidos TEXT DEFAULT '',
        UNIQUE(profesor_id,materia_id,seccion), FOREIGN KEY(profesor_id) REFERENCES profesores(id) ON DELETE CASCADE,
        FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS asignaciones_horario (id INTEGER PRIMARY KEY AUTOINCREMENT,
        carga_id INTEGER NOT NULL, profesor_id INTEGER NOT NULL, materia_id INTEGER NOT NULL,
        salon_id INTEGER NOT NULL, dia TEXT NOT NULL, hora_inicio TEXT NOT NULL, hora_fin TEXT NOT NULL,
        estado TEXT DEFAULT 'Confirmado', FOREIGN KEY(carga_id) REFERENCES carga_academica(id) ON DELETE CASCADE,
        FOREIGN KEY(profesor_id) REFERENCES profesores(id) ON DELETE CASCADE,
        FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE,
        FOREIGN KEY(salon_id) REFERENCES salones(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT);
    CREATE INDEX IF NOT EXISTS idx_asignaciones_dia ON asignaciones_horario(dia);
    CREATE INDEX IF NOT EXISTS idx_asignaciones_profesor ON asignaciones_horario(profesor_id);
    CREATE INDEX IF NOT EXISTS idx_asignaciones_salon ON asignaciones_horario(salon_id);
    CREATE INDEX IF NOT EXISTS idx_asignaciones_materia ON asignaciones_horario(materia_id);
    CREATE INDEX IF NOT EXISTS idx_carga_profesor ON carga_academica(profesor_id);
    CREATE INDEX IF NOT EXISTS idx_materias_carrera ON materias(carrera_id);
    CREATE INDEX IF NOT EXISTS idx_plan_carrera ON planes_estudio(carrera_id);
    """)
    for tabla, columna, ddl in [
        ("carreras", "codigo", "TEXT DEFAULT ''"),
        ("planes_estudio", "ciclo", "TEXT DEFAULT ''"),
    ]:
        cols = {r["name"] for r in _sqlite_query(f"PRAGMA table_info({tabla})")}
        if columna not in cols:
            _sqlite_execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}")


# ──────────────────── Configuración persistente ────────────────────

def get_config(clave: str, default: str = "") -> str:
    """Lee un ajuste persistente de la tabla ``configuracion`` (SQLite o Supabase)."""
    try:
        rows = query("SELECT valor FROM configuracion WHERE clave = ? LIMIT 1", (str(clave),))
        if rows and rows[0].get("valor") is not None:
            return str(rows[0]["valor"])
    except Exception:
        pass
    return default


def set_config(clave: str, valor: str) -> None:
    """Guarda o actualiza un ajuste persistente en la tabla ``configuracion``."""
    clave_str = str(clave)
    valor_str = str(valor)
    existe = query("SELECT clave FROM configuracion WHERE clave = ? LIMIT 1", (clave_str,))
    if existe:
        execute("UPDATE configuracion SET valor = ? WHERE clave = ?", (valor_str, clave_str))
    else:
        execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)", (clave_str, valor_str))


def delete_config(clave: str) -> None:
    """Elimina un ajuste de la tabla ``configuracion``."""
    borrar_donde("configuracion", "clave", str(clave))


# ─────────────────────────── helpers de dominio ───────────────────────────

def normalizar(texto: Any) -> str:
    if not texto:
        return ""
    t = "".join(c for c in unicodedata.normalize("NFD", str(texto))
                if unicodedata.category(c) != "Mn")
    return " ".join(t.upper().replace("À", "A").split())


def _clave_carrera_suave(texto: Any) -> str:
    t = normalizar(texto)
    t = re.sub(r"\s*[-–—:/]+\s*", " - ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    return t


_ALIAS_CARRERAS_NORM: Dict[str, str] = {}
for _c in CARRERAS_CANONICAS:
    _ALIAS_CARRERAS_NORM[_clave_carrera_suave(_c)] = _c
for _k, _v in _ALIAS_CARRERAS_RAW.items():
    _ALIAS_CARRERAS_NORM[_clave_carrera_suave(_k)] = _v


def nombre_carrera_canonico(texto: Any) -> str:
    limpio = " ".join(str(texto or "").strip().split())
    if not limpio:
        return ""
    if "/" in limpio:
        limpio = limpio.split("/")[0].strip()
    clave = _clave_carrera_suave(limpio)
    if clave in _ALIAS_CARRERAS_NORM:
        return _ALIAS_CARRERAS_NORM[clave]
    if "FISIOTERAPIA" in clave:
        return "PNF Fisioterapia"
    if "VETERINARIA" in clave:
        return "PNF Veterinaria"
    if "AGROECOLOGIA" in clave:
        return "PNF Agroecología"
    if "RECURSOS HUMANOS" in clave or "RRHH" in clave or "R.R.H.H" in clave:
        return "Administración - Administración de Recursos Humanos"
    if "MATERIALES" in clave and "FINANCIERO" in clave:
        return "Administración - Recursos Materiales y Financieros"
    if "ORGANIZACION" in clave and "SISTEMA" in clave:
        return "Administración - Organización y Sistemas"
    if "MERCADEO" in clave and ("ADMIN" in clave or "MENCION" in clave or clave == "MERCADEO"):
        return "Administración - Mercadeo"
    if "INFORMATICA" in clave and ("ADMIN" in clave or "MENCION" in clave or clave == "INFORMATICA"):
        return "Administración - Informática"
    if "MATEMATICA" in clave and ("EDUC" in clave or "DOCENCIA" in clave or "MENCION" in clave or clave in ("MATEMATICA", "MATEMATICAS")):
        return "Educación - Docencia en Matemáticas"
    if "INGLES" in clave and ("EDUC" in clave or "DOCENCIA" in clave or "MENCION" in clave or clave in ("INGLES", "IDIOMA INGLES")):
        return "Educación - Docencia en Idioma Inglés"
    if "EDUCACION INICIAL" in clave or ("EDUC" in clave and "INICIAL" in clave):
        return "Educación Inicial - Sin Mención"
    if "EDUCACION INTEGRAL" in clave or ("EDUC" in clave and "INTEGRAL" in clave):
        return "Educación Integral - Sin Mención"
    return limpio


def facultad_de_carrera(nombre_carrera: str) -> str:
    canon = nombre_carrera_canonico(nombre_carrera)
    clave = normalizar(canon)
    if clave.startswith("PNF") or any(k in clave for k in ("FISIOTERAPIA", "VETERINARIA", "AGROECOLOGIA")):
        return "Programas Nacionales de Formación (PNF)"
    if clave.startswith("EDUCACION"):
        return "Facultad de Ciencias de la Educación"
    return "Facultad de Ciencias Económicas y Sociales"


def buscar_carrera_existente(nombre: Any) -> Optional[Dict[str, Any]]:
    canon = nombre_carrera_canonico(nombre)
    if not canon:
        return None
    clave_obj = _clave_carrera_suave(canon)
    clave_raw = _clave_carrera_suave(nombre)
    carreras = query("SELECT id, nombre, facultad_id FROM carreras ORDER BY id")
    for c in carreras:
        if c["nombre"] == canon:
            return c
    for c in carreras:
        ck = _clave_carrera_suave(nombre_carrera_canonico(c["nombre"]))
        if ck in (clave_obj, clave_raw) or _clave_carrera_suave(c["nombre"]) in (clave_obj, clave_raw):
            return c
    return None


def get_or_create_carrera_segura(nombre: Any, permitir_crear: bool = True) -> Optional[int]:
    canon = nombre_carrera_canonico(nombre)
    if not canon:
        return None
    existente = buscar_carrera_existente(canon)
    if existente:
        return int(existente["id"])
    if not permitir_crear:
        return None
    fac_id = get_or_create("facultades", "nombre", facultad_de_carrera(canon))
    return get_or_create("carreras", "nombre", canon, {"facultad_id": fac_id})


def normalizar_entero(valor: Any, *, minimo: int = 0, maximo: Optional[int] = None,
                      default: Optional[int] = 0) -> int:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if default is None:
            raise ValueError("El valor numérico es obligatorio.")
        return int(default)
    if isinstance(valor, bool):
        raise ValueError("El valor debe ser un número entero.")
    if isinstance(valor, int):
        numero = valor
    elif isinstance(valor, float):
        if not valor.is_integer():
            raise ValueError(f"'{valor}' no es un número entero.")
        numero = int(valor)
    else:
        texto = str(valor).strip()
        if not re.fullmatch(r"[+-]?\d+", texto):
            raise ValueError(f"'{texto}' no es un número entero válido.")
        numero = int(texto)
    if numero < minimo or (maximo is not None and numero > maximo):
        rango = f" entre {minimo} y {maximo}" if maximo is not None else f" mayor o igual a {minimo}"
        raise ValueError(f"El valor debe ser{rango}.")
    return numero


def normalizar_cedula(valor: Any) -> str:
    if valor is None:
        return ""
    texto = " ".join(str(valor).strip().upper().split())
    if not texto:
        return ""
    if not (re.fullmatch(r"[VE][ -]?\d{7,8}", texto)
            or re.fullmatch(r"[VE][ -]?\d{1,3}(?:\.\d{3}){1,2}", texto)):
        raise ValueError("Cédula inválida. Ejemplos: V-1234567 o V-1.234.567.")
    digitos = re.sub(r"\D", "", texto[1:])
    if not 7 <= len(digitos) <= 8:
        raise ValueError("La cédula debe tener 7 u 8 dígitos.")
    return f"{texto[0]}-{digitos}"


SECTORES_AMBIENTE: Tuple[Tuple[str, int], ...] = (
    ("Piso 1", 1),
    ("Piso 2", 2),
    ("Piso 3", 3),
    ("Piso 4", 4),
    ("Satelitales", 5),
    ("Planta Baja (PB)", 6),
    ("Virtuales", 7),
    ("Laboratorios y Otros", 8),
)


def categoria_ambiente(codigo: Any) -> Tuple[str, int]:
    c = str(codigo or "").strip().strip("´'`\"").upper()
    for prefijo in ("P1.", "P2.", "P3.", "P4."):
        if c.startswith(prefijo):
            c = prefijo[:2] + "-" + c[3:]
    if (c.startswith("P1-") or c.startswith("P1") or "PISO 1" in c
            or c.startswith("AULA 1")):
        return "Piso 1", 1
    if (c.startswith("P2-") or c.startswith("P2") or "PISO 2" in c
            or c.startswith("AULA 2")):
        return "Piso 2", 2
    if (c.startswith("P3-") or c.startswith("P3") or "PISO 3" in c
            or c.startswith("AULA 3") or "MAGNA" in c):
        return "Piso 3", 3
    if (c.startswith("P4-") or c.startswith("P4") or "PISO 4" in c
            or c.startswith("AULA 4")):
        return "Piso 4", 4
    if "SATELITAL" in c:
        return "Satelitales", 5
    if c.startswith("PB") or "PLANTA BAJA" in c:
        return "Planta Baja (PB)", 6
    if "VIRTUAL" in c or "ONLINE" in c:
        return "Virtuales", 7
    return "Laboratorios y Otros", 8


def clave_orden_ambiente(codigo: Any) -> List[Tuple[int, Any]]:
    c = str(codigo or "").strip().strip("´'`\"").upper()
    return [(0, int(t)) if t.isdigit() else (1, normalizar(t))
            for t in re.split(r"(\d+)", c) if t != ""]


def ordenar_ambientes(filas: Iterable[Dict], campo: str = "codigo") -> List[Dict]:
    return sorted(
        filas,
        key=lambda f: (categoria_ambiente(f.get(campo))[1],
                       clave_orden_ambiente(f.get(campo)),
                       str(f.get("id") or "")),
    )


def ambientes_oficiales(filas: Iterable[Dict], campo: str = "codigo") -> List[Dict]:
    permitidos = set(AMBIENTES_OFICIALES)
    return ordenar_ambientes(
        [f for f in filas if str(f.get(campo) or "").strip().upper() in permitidos],
        campo,
    )


def agrupar_ambientes(filas: Iterable[Dict], campo: str = "codigo") -> List[Dict]:
    por_sector: Dict[str, List[Dict]] = {}
    for fila in ordenar_ambientes(filas, campo):
        sector, _ = categoria_ambiente(fila.get(campo))
        por_sector.setdefault(sector, []).append(fila)
    return [
        {"sector": sector, "total": len(por_sector[sector]), "filas": por_sector[sector]}
        for sector, _prioridad in SECTORES_AMBIENTE
        if sector in por_sector
    ]


def get_or_create(table: str, field: str, value: str, extra: Optional[Dict] = None) -> int:
    extra = extra or {}
    val_limpio = " ".join(str(value or "").strip().split())
    if table == "carreras" and field == "nombre":
        existente = buscar_carrera_existente(val_limpio)
        if existente:
            return int(existente["id"])
        val_limpio = nombre_carrera_canonico(val_limpio) or val_limpio
    else:
        rows = query(f"SELECT id FROM {table} WHERE {field} = ? LIMIT 1", (val_limpio,))
        if rows:
            return int(rows[0]["id"])
        if table in ("facultades", "profesores") and field == "nombre":
            objetivo = normalizar(val_limpio)
            for r in query(f"SELECT id, {field} FROM {table}"):
                if normalizar(r.get(field)) == objetivo:
                    return int(r["id"])
    cols = [field] + list(extra)
    vals = [val_limpio] + list(extra.values())
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
    rid = execute(sql, vals)
    if not rid:
        rows = query(f"SELECT id FROM {table} WHERE {field} = ? LIMIT 1", (val_limpio,))
        rid = rows[0]["id"] if rows else 0
    return int(rid)


def get_or_create_materia(nombre: str, carrera_id: int, codigo: str = "",
                          semestre: str = "1er Semestre", creditos: int = 0) -> int:
    creditos = normalizar_entero(creditos, minimo=0, maximo=30, default=0)
    nombre_limpio = " ".join(str(nombre or "").strip().split())
    cod_limpio = str(codigo or "").strip()
    sem_limpio = str(semestre or "").strip() or "1er Semestre"

    encontrada: Optional[Dict[str, Any]] = None
    rows = query(
        "SELECT id, nombre, codigo, semestre, unidad_credito FROM materias "
        "WHERE carrera_id = ? ORDER BY id",
        (int(carrera_id),),
    )
    objetivo = normalizar(nombre_limpio)
    for r in rows:
        if r["nombre"] == nombre_limpio:
            encontrada = r
            break
    if encontrada is None:
        for r in rows:
            if normalizar(r["nombre"]) == objetivo:
                encontrada = r
                break

    if encontrada is not None:
        mid = int(encontrada["id"])
        cod_final = cod_limpio or (encontrada.get("codigo") or "")
        uc_actual = int(encontrada.get("unidad_credito") or 0)
        uc_final = creditos if creditos > 0 else uc_actual
        sem_actual = str(encontrada.get("semestre") or "").strip()
        sem_final = sem_actual or sem_limpio
        if (cod_final != (encontrada.get("codigo") or "")
                or uc_final != uc_actual
                or sem_final != sem_actual):
            execute(
                "UPDATE materias SET codigo=?, unidad_credito=?, semestre=? WHERE id=?",
                (cod_final, uc_final, sem_final, mid),
            )
        return mid

    return int(execute(
        "INSERT INTO materias (nombre,codigo,carrera_id,semestre,unidad_credito) VALUES (?,?,?,?,?)",
        (nombre_limpio, cod_limpio, int(carrera_id), sem_limpio, creditos)))


def _fusionar_materia_en(origen_id: int, destino_id: int) -> None:
    if origen_id == destino_id:
        return
    m_orig = query("SELECT codigo, unidad_credito, semestre FROM materias WHERE id=?", (origen_id,))
    m_dest = query("SELECT codigo, unidad_credito, semestre FROM materias WHERE id=?", (destino_id,))
    if m_orig and m_dest:
        o, d = m_orig[0], m_dest[0]
        cod = (d.get("codigo") or "") or (o.get("codigo") or "")
        uc = int(d.get("unidad_credito") or 0) or int(o.get("unidad_credito") or 0)
        sem = (d.get("semestre") or "") or (o.get("semestre") or "1er Semestre")
        execute("UPDATE materias SET codigo=?, unidad_credito=?, semestre=? WHERE id=?",
                (cod, uc, sem, destino_id))

    for ca in query("SELECT * FROM carga_academica WHERE materia_id=?", (origen_id,)):
        cid_orig = int(ca["id"])
        existe = query(
            "SELECT id FROM carga_academica WHERE profesor_id=? AND materia_id=? AND seccion=? LIMIT 1",
            (int(ca["profesor_id"]), destino_id, ca["seccion"]),
        )
        if existe:
            cid_dest = int(existe[0]["id"])
            for a in query("SELECT id FROM asignaciones_horario WHERE carga_id=?", (cid_orig,)):
                execute(
                    "UPDATE asignaciones_horario SET carga_id=?, materia_id=? WHERE id=?",
                    (cid_dest, destino_id, int(a["id"])),
                )
            execute("DELETE FROM carga_academica WHERE id=?", (cid_orig,))
        else:
            execute("UPDATE carga_academica SET materia_id=? WHERE id=?", (destino_id, cid_orig))

    for a in query("SELECT id FROM asignaciones_horario WHERE materia_id=?", (origen_id,)):
        execute("UPDATE asignaciones_horario SET materia_id=? WHERE id=?", (destino_id, int(a["id"])))

    execute("DELETE FROM materias WHERE id=?", (origen_id,))


def recuperar_pensum_desde_respaldos_locales() -> int:
    if backend_activo() != "sqlite":
        return 0
    candidatos = [
        DATA_DIR / "universidad_horarios_backup.db",
        RECURSOS / "data" / "universidad_horarios_backup.db",
        DATA_DIR / "universidad_horarios_antes_pnf.db",
        RECURSOS / "data" / "universidad_horarios_antes_pnf.db",
    ]
    carpeta_bk = DB_PATH.parent / "backups"
    if carpeta_bk.exists():
        candidatos.extend(sorted(carpeta_bk.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[:5])

    recuperadas = 0
    carreras_actuales = {
        _clave_carrera_suave(nombre_carrera_canonico(c["nombre"])): int(c["id"])
        for c in query("SELECT id, nombre FROM carreras")
    }
    planes_por_car: Dict[int, set] = {}
    for p in query("SELECT carrera_id, codigo, nombre FROM planes_estudio"):
        planes_por_car.setdefault(int(p["carrera_id"]), set()).add(
            (str(p.get("codigo") or "").strip(), normalizar(p.get("nombre")))
        )

    for bk in candidatos:
        if not bk.exists() or bk.resolve() == DB_PATH.resolve():
            continue
        try:
            conn = sqlite3.connect(bk, timeout=10)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT c.nombre AS carrera, p.codigo, p.nombre, p.unidad_credito,
                          p.horas_teoria, p.horas_practica, p.ciclo, p.opcionalidad,
                          p.tecnica, p.prelacion
                   FROM planes_estudio p
                   JOIN carreras c ON c.id = p.carrera_id"""
            ).fetchall()
            conn.close()
        except Exception:
            continue

        for r in rows:
            canon = nombre_carrera_canonico(r["carrera"])
            if canon not in CARRERAS_CANONICAS:
                continue
            clave_car = _clave_carrera_suave(canon)
            car_id = carreras_actuales.get(clave_car)
            if car_id is None:
                car_id = get_or_create_carrera_segura(canon, permitir_crear=True)
                if car_id is None:
                    continue
                carreras_actuales[clave_car] = car_id

            cod = str(r["codigo"] or "").strip()
            nom = " ".join(str(r["nombre"] or "").strip().split())
            if not nom:
                continue
            k_plan = (cod, normalizar(nom))
            vistos = planes_por_car.setdefault(car_id, set())
            if k_plan in vistos:
                continue
            uc = int(r["unidad_credito"] or 0)
            ht = int(r["horas_teoria"] or 0)
            hp = int(r["horas_practica"] or 0)
            cic = str(r["ciclo"] or "").strip()
            opc = str(r["opcionalidad"] or "").strip()
            tec = str(r["tecnica"] or "").strip()
            prel = str(r["prelacion"] or "").strip()
            execute(
                """INSERT INTO planes_estudio
                   (carrera_id,codigo,nombre,unidad_credito,horas_teoria,horas_practica,
                    ciclo,opcionalidad,tecnica,prelacion)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (car_id, cod, nom, uc, ht, hp, cic, opc, tec, prel),
            )
            get_or_create_materia(nom, car_id, cod, cic or "1er Semestre", uc)
            vistos.add(k_plan)
            recuperadas += 1
    return recuperadas


def sanear_carreras_duplicadas() -> Dict[str, Any]:
    respaldo = respaldar_bd("antes_sanear")
    stats: Dict[str, Any] = {
        "carreras_fusionadas": 0,
        "carreras_vacias_eliminadas": 0,
        "materias_fusionadas": 0,
        "carreras_renombradas": 0,
        "respaldo": str(respaldo.name) if respaldo else "",
    }
    try:
        carreras = query("SELECT id, nombre, facultad_id, codigo FROM carreras ORDER BY id")
        if not carreras:
            return stats

        planes_cnt: Dict[int, int] = {}
        for p in query("SELECT carrera_id FROM planes_estudio"):
            cid = int(p["carrera_id"])
            planes_cnt[cid] = planes_cnt.get(cid, 0) + 1
        mats_cnt: Dict[int, int] = {}
        for m in query("SELECT carrera_id FROM materias"):
            cid = int(m["carrera_id"])
            mats_cnt[cid] = mats_cnt.get(cid, 0) + 1

        grupos: Dict[str, List[Dict]] = {}
        for c in carreras:
            canon = nombre_carrera_canonico(c["nombre"])
            clave = _clave_carrera_suave(canon)
            grupos.setdefault(clave, []).append(c)

        for clave, lista in grupos.items():
            lista.sort(key=lambda c: (
                -planes_cnt.get(int(c["id"]), 0),
                -mats_cnt.get(int(c["id"]), 0),
                int(c["id"]),
            ))
            keep = lista[0]
            keep_id = int(keep["id"])
            nombre_canon = nombre_carrera_canonico(keep["nombre"])

            if (len(lista) == 1
                    and nombre_canon not in CARRERAS_CANONICAS
                    and planes_cnt.get(keep_id, 0) == 0
                    and mats_cnt.get(keep_id, 0) == 0):
                execute("DELETE FROM carreras WHERE id=?", (keep_id,))
                stats["carreras_vacias_eliminadas"] += 1
                continue

            for dup in lista[1:]:
                dup_id = int(dup["id"])
                planes_keep = query(
                    "SELECT id, codigo, nombre, unidad_credito, horas_teoria, horas_practica, ciclo "
                    "FROM planes_estudio WHERE carrera_id=?",
                    (keep_id,),
                )
                mapa_plan = {
                    (str(p.get("codigo") or "").strip(), normalizar(p.get("nombre"))): p
                    for p in planes_keep
                }
                for p in query("SELECT * FROM planes_estudio WHERE carrera_id=?", (dup_id,)):
                    pid = int(p["id"])
                    k_plan = (str(p.get("codigo") or "").strip(), normalizar(p.get("nombre")))
                    if k_plan in mapa_plan:
                        ex = mapa_plan[k_plan]
                        uc = int(ex.get("unidad_credito") or 0) or int(p.get("unidad_credito") or 0)
                        ht = int(ex.get("horas_teoria") or 0) or int(p.get("horas_teoria") or 0)
                        hp = int(ex.get("horas_practica") or 0) or int(p.get("horas_practica") or 0)
                        cic = (ex.get("ciclo") or "") or (p.get("ciclo") or "")
                        execute(
                            "UPDATE planes_estudio SET unidad_credito=?, horas_teoria=?, "
                            "horas_practica=?, ciclo=? WHERE id=?",
                            (uc, ht, hp, cic, int(ex["id"])),
                        )
                        execute("DELETE FROM planes_estudio WHERE id=?", (pid,))
                    else:
                        execute("UPDATE planes_estudio SET carrera_id=? WHERE id=?", (keep_id, pid))
                        mapa_plan[k_plan] = p

                mats_keep = query("SELECT id, nombre FROM materias WHERE carrera_id=?", (keep_id,))
                mapa_mat = {normalizar(m["nombre"]): int(m["id"]) for m in mats_keep}
                for m in query("SELECT id, nombre FROM materias WHERE carrera_id=?", (dup_id,)):
                    mid = int(m["id"])
                    km = normalizar(m["nombre"])
                    if km in mapa_mat:
                        _fusionar_materia_en(mid, mapa_mat[km])
                        stats["materias_fusionadas"] += 1
                    else:
                        execute("UPDATE materias SET carrera_id=? WHERE id=?", (keep_id, mid))
                        mapa_mat[km] = mid

                execute("DELETE FROM carreras WHERE id=?", (dup_id,))
                stats["carreras_fusionadas"] += 1

            mats_finales = query("SELECT id, nombre FROM materias WHERE carrera_id=? ORDER BY id", (keep_id,))
            vistos_m: Dict[str, int] = {}
            for m in mats_finales:
                km = normalizar(m["nombre"])
                mid = int(m["id"])
                if km in vistos_m:
                    _fusionar_materia_en(mid, vistos_m[km])
                    stats["materias_fusionadas"] += 1
                else:
                    vistos_m[km] = mid

            fac_id = get_or_create("facultades", "nombre", facultad_de_carrera(nombre_canon))
            if keep["nombre"] != nombre_canon or int(keep["facultad_id"]) != fac_id:
                execute("UPDATE carreras SET nombre=?, facultad_id=? WHERE id=?",
                        (nombre_canon, fac_id, keep_id))
                stats["carreras_renombradas"] += 1
    except Exception:
        restaurar_bd(respaldo)
        raise
    return stats


def _borrar_tablas(tablas: List[str]) -> None:
    if backend_activo() == "sqlite":
        conn = _sqlite_conn()
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            for tabla in tablas:
                conn.execute(f"DELETE FROM {tabla}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" %
                         ",".join("?" for _ in tablas), tuple(tablas))
            conn.commit()
        finally:
            conn.close()
    else:
        for tabla in tablas:
            _rest(tabla, "DELETE", {"id": "gte.1"})


def limpiar_carga_academica() -> None:
    respaldar_bd("antes_vaciar")
    _borrar_tablas(["asignaciones_horario", "carga_academica", "disponibilidades"])


def clear_all_data(keep_salones: bool = True) -> None:
    respaldar_bd("antes_borrar_todo")
    tablas = ["asignaciones_horario", "carga_academica", "disponibilidades",
              "planes_estudio", "materias", "profesores", "carreras", "facultades"]
    if not keep_salones:
        tablas.insert(0, "salones")
    _borrar_tablas(tablas)


def estadisticas() -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for key, sql in {
        "carreras": "SELECT COUNT(*) n FROM carreras",
        "profesores": "SELECT COUNT(*) n FROM profesores",
        "materias": "SELECT COUNT(*) n FROM materias",
        "planes_estudio": "SELECT COUNT(*) n FROM planes_estudio",
        "salones": "SELECT COUNT(*) n FROM salones",
        "clases_programadas": "SELECT COUNT(*) n FROM asignaciones_horario",
        "ambientes_en_uso": "SELECT COUNT(DISTINCT salon_id) n FROM asignaciones_horario",
        "profesores_activos": "SELECT COUNT(DISTINCT profesor_id) n FROM asignaciones_horario",
    }.items():
        try:
            stats[key] = int(query(sql)[0]["n"])
        except Exception:
            stats[key] = 0
    return stats
