"""Migra la BD SQLite local a Supabase respetando todas las claves foráneas.

Pasos previos:
  1. cp .env.example .env  y llena SUPABASE_URL / SUPABASE_KEY (service_role).
  2. Supabase -> SQL Editor -> ejecuta sql/schema.sql.
  3. python scripts/migrate_to_supabase.py [--limpiar] [--plan]

Usa PostgREST (HTTPS): no necesita psycopg ni DLLs nativas en Windows.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, importers, pdf_importers, scheduler  # noqa: E402

# Orden respetando dependencias (Padres primero)
TABLAS = ["facultades", "carreras", "salones", "profesores", "disponibilidades",
          "planes_estudio", "materias", "carga_academica", "asignaciones_horario",
          "configuracion"]

FK = {
    "carreras": {"facultad_id": "facultades"},
    "disponibilidades": {"profesor_id": "profesores"},
    "planes_estudio": {"carrera_id": "carreras"},
    "materias": {"carrera_id": "carreras"},
    "carga_academica": {"profesor_id": "profesores", "materia_id": "materias"},
    "asignaciones_horario": {"carga_id": "carga_academica", "profesor_id": "profesores",
                             "materia_id": "materias", "salon_id": "salones"},
}


def migrar(limpiar: bool = False, plan: bool = False, pnf: bool = False) -> None:
    cfg = db.configuracion()
    if not cfg.get("SUPABASE_URL") or not cfg.get("SUPABASE_KEY"):
        raise SystemExit("Faltan SUPABASE_URL/SUPABASE_KEY en .env")
    # El origen siempre es el SQLite local (se lee con _sqlite_query, nunca por
    # PostgREST), así que 'auto' con credenciales también es válido aquí.
    if db.backend_activo() not in ("sqlite", "supabase"):
        raise SystemExit("DB_BACKEND desconocido; usa auto, sqlite o supabase.")

    print("Verificando esquema en Supabase…")
    try:
        db._rest("facultades", "GET", {"select": "id", "limit": 1})
    except Exception as exc:
        raise SystemExit(
            "Faltan las tablas en Supabase. Ve a SQL Editor → New query, pega "
            "TODO el contenido de sql/schema.sql y pulsa Run.\n"
            f"Detalle: {str(exc)[:200]}"
        )

    # El pensum se importa en SQLITE (local, rápido) y se sube junto con el
    # resto. Hacerlo contra Supabase serían ~2000 llamadas REST y agota el
    # tiempo de espera; además la BD semilla ya trae plan 2024 + 3 PNF.
    if plan or pnf:
        print("Actualizando pensum en SQLite local…")
        os.environ["DB_BACKEND"] = "sqlite"
        db._invalidar_cache()
        if plan:
            r = importers.importar_plan_estudio()
            print(f"  ✓ plan 2024: {r['total']} filas")
        if plan or pnf:
            r = pdf_importers.importar_pnfs()
            print(f"  ✓ PNF: {sum(r.values())} unidades "
                  f"({r.get('fisioterapia', 0)} Fisioterapia, "
                  f"{r.get('veterinaria', 0)} Veterinaria, "
                  f"{r.get('agroecologia', 0)} Agroecología)")
        print("Regenerando asignaciones en SQLite local…")
        r = scheduler.generar_horarios_automaticos()
        print(f"  ✓ {r['asignados']} asignadas, {r['pendientes']} pendientes")

    print("Leyendo SQLite…")
    origen: dict = {}
    for t in TABLAS:
        try:
            origen[t] = db._sqlite_query(f"SELECT * FROM {t}")
        except Exception:
            origen[t] = []
        print(f"  {t}: {len(origen[t])} filas")

    if limpiar:
        print("Limpiando Supabase…")
        for t in reversed(TABLAS):
            # 'configuracion' no tiene columna id (su PK es 'clave').
            filtro = {"clave": "not.is.null"} if t == "configuracion" else {"id": "gte.1"}
            try:
                db._rest(t, "DELETE", filtro)
            except Exception as exc:
                print(f"  !No se pudo limpiar {t}: {exc}")

    print("Subiendo datos…")
    os.environ["DB_BACKEND"] = "supabase"
    id_map: dict = {}

    for tabla in TABLAS:
        creados = 0
        for fila in origen.get(tabla, []):
            datos = dict(fila)
            old_id = datos.pop("id", None)
            for campo, tabla_padre in FK.get(tabla, {}).items():
                valor = datos.get(campo)
                if valor is not None and int(valor) in id_map.get(tabla_padre, {}):
                    datos[campo] = id_map[tabla_padre][int(valor)]
            try:
                respuesta = db._rest(tabla, "POST", body=datos)
                nuevo_id = None
                if isinstance(respuesta, list) and respuesta:
                    nuevo_id = respuesta[0].get("id")
                if nuevo_id is not None and old_id is not None:
                    id_map.setdefault(tabla, {})[int(old_id)] = int(nuevo_id)
                creados += 1
            except Exception as exc:
                print(f"  ! {tabla} id={old_id}: {str(exc)[:200]}")
        print(f"  ✓ {tabla}: {creados} filas")

    print("\nMigración completada. Ahora usa DB_BACKEND=supabase en .env.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limpiar", action="store_true")
    p.add_argument("--plan", action="store_true", help="Importa el pensum 2024 y los 3 PNF")
    p.add_argument("--pnf", action="store_true", help="Importa solo los 3 PNF desde los PDFs")
    a = p.parse_args()
    migrar(a.limpiar, a.plan, a.pnf)
