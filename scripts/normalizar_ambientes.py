"""Deja el inventario de ambientes solo con los 41 salones oficiales.

Los salones oficiales son (numeración global y consecutiva):
    P1-01..P1-08, P2-09..P2-22, P3-23..P3-27, P4-28..P4-37,
    SATELITAL-01, SATELITAL-02, VIRTUAL-01, VIRTUAL-02.

Las clases asignadas a cualquier otro ambiente se reubican en un salón oficial:
se prefiere el mismo piso y, ante todo, se evita que dos clases ocupen el mismo
ambiente en el mismo día/hora. Los ambientes compartibles (SATELITAL/VIRTUAL)
se usan como último recurso para las clases de piso y como destino natural de
PB, coordinaciones, cancha, etc. Las capacidades de los salones oficiales NO se
modifican.

Uso:
    .venv/bin/python scripts/normalizar_ambientes.py            # simulación
    .venv/bin/python scripts/normalizar_ambientes.py --apply    # aplicar
    DB_BACKEND=sqlite .venv/bin/python scripts/normalizar_ambientes.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, scheduler  # noqa: E402

PISOS = {
    1: [f"P1-{n:02d}" for n in range(1, 9)],
    2: [f"P2-{n:02d}" for n in range(9, 23)],
    3: [f"P3-{n:02d}" for n in range(23, 28)],
    4: [f"P4-{n:02d}" for n in range(28, 38)],
}
OFICIALES = ([c for piso in (1, 2, 3, 4) for c in PISOS[piso]]
             + ["SATELITAL-01", "SATELITAL-02", "VIRTUAL-01", "VIRTUAL-02"])
COMPARTIBLES = {"SATELITAL-01", "SATELITAL-02", "VIRTUAL-01", "VIRTUAL-02"}
PLAN = Path("/tmp/opencode/reasignacion_ambientes.json")


def _norm(codigo: object) -> str:
    return str(codigo or "").strip().strip("´'`\"").upper()


def _piso(codigo: object) -> int | None:
    m = re.match(r"P([1-4])", _norm(codigo))
    return int(m.group(1)) if m else None


def _solapa(a: dict, b: dict) -> bool:
    if db.normalizar(a.get("dia")) != db.normalizar(b.get("dia")):
        return False
    return (scheduler._a_minutos(a.get("hora_inicio")) < scheduler._a_minutos(b.get("hora_fin"))
            and scheduler._a_minutos(b.get("hora_inicio")) < scheduler._a_minutos(a.get("hora_fin")))


def _destinos(codigo: str) -> list[str]:
    c = _norm(codigo)
    piso = _piso(c)
    if piso:
        # Primero el mismo piso; los compartibles solo si no hay hueco en él.
        return PISOS[piso] + ["SATELITAL-01", "SATELITAL-02", "VIRTUAL-01", "VIRTUAL-02"]
    if "VIRTUAL" in c or "ONLINE" in c:
        return ["VIRTUAL-01", "VIRTUAL-02"]
    return ["SATELITAL-01", "SATELITAL-02"]


def construir_plan() -> dict:
    salones = db.query("SELECT id,codigo,capacidad,edificio,es_camillas FROM salones")
    por_codigo = {_norm(s["codigo"]): s for s in salones}
    por_id = {int(s["id"]): s for s in salones}
    faltan = [c for c in OFICIALES if c not in por_codigo]
    if faltan:
        raise SystemExit(f"Faltan salones oficiales en la BD: {faltan}")

    asignaciones = db.query(
        "SELECT id,salon_id,dia,hora_inicio,hora_fin FROM asignaciones_horario")
    ids_oficiales = {int(por_codigo[c]["id"]) for c in OFICIALES}
    ocupacion: dict[int, list[dict]] = {sid: [] for sid in ids_oficiales}
    uso: dict[int, int] = {sid: 0 for sid in ids_oficiales}
    for a in asignaciones:
        sid = int(a["salon_id"])
        if sid in ids_oficiales:
            ocupacion[sid].append(a)
            uso[sid] += 1

    movimientos = []
    extras = [a for a in asignaciones if int(a["salon_id"]) not in ids_oficiales]
    for a in sorted(extras, key=lambda x: int(x["id"])):
        anterior = por_id[int(a["salon_id"])]
        codigo_anterior = _norm(anterior["codigo"])
        piso_anterior = _piso(codigo_anterior)
        mejor = None
        for codigo in _destinos(codigo_anterior):
            sala = por_codigo[codigo]
            sid = int(sala["id"])
            choques = (0 if codigo in COMPARTIBLES
                       else sum(1 for otra in ocupacion[sid] if _solapa(a, otra)))
            score = (
                choques,
                0 if _piso(codigo) == piso_anterior else 1,
                abs(int(sala.get("capacidad") or 0) - int(anterior.get("capacidad") or 0)),
                uso[sid],
                OFICIALES.index(codigo),
            )
            if mejor is None or score < mejor[0]:
                mejor = (score, sid, codigo, choques)
        _score, sid, codigo, choques = mejor
        ocupacion[sid].append(a)
        uso[sid] += 1
        movimientos.append({
            "asignacion_id": int(a["id"]),
            "desde": codigo_anterior,
            "hacia": codigo,
            "salon_id": sid,
            "choques": choques,
        })

    extras_salones = [
        {"id": int(s["id"]), "codigo": s["codigo"], "capacidad": s["capacidad"],
         "edificio": s.get("edificio", ""), "es_camillas": s.get("es_camillas", 0)}
        for s in salones if int(s["id"]) not in ids_oficiales
    ]
    return {
        "backend": db.backend_activo(),
        "oficiales": OFICIALES,
        "capacidades_oficiales": {c: por_codigo[c]["capacidad"] for c in OFICIALES},
        "movimientos": movimientos,
        "extras_salones": extras_salones,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Aplicar los cambios (por defecto solo simula)")
    args = ap.parse_args()

    plan = construir_plan()
    movimientos = plan["movimientos"]
    destinos = Counter(m["hacia"] for m in movimientos)
    print(f"Backend: {plan['backend']}")
    print(f"Salones oficiales: {len(OFICIALES)} | extra a eliminar: {len(plan['extras_salones'])}")
    print(f"Clases a reubicar: {len(movimientos)} | total asignaciones: "
          f"{len(movimientos) + _clases_oficiales()}")
    print(f"Clases con solape inevitable en el destino: {sum(m['choques'] for m in movimientos)}")
    print("Reparto por salón oficial:")
    for codigo in OFICIALES:
        print(f"  {codigo:14} recibe {destinos.get(codigo, 0):3} | capacidad {plan['capacidades_oficiales'][codigo]}")
    print("Ejemplos:", [(m["desde"], m["hacia"]) for m in movimientos[:8]])

    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Plan reversible guardado en {PLAN} (fuera del repo)")

    if not args.apply:
        print("Simulación terminada. Nada se modificó. Usa --apply para aplicar.")
        return

    db.exec_many("UPDATE asignaciones_horario SET salon_id=? WHERE id=?",
                 [(m["salon_id"], m["asignacion_id"]) for m in movimientos])
    for sala in plan["extras_salones"]:
        db.borrar_donde("salones", "id", sala["id"])

    salones = db.query("SELECT codigo,capacidad FROM salones")
    capacidades = {_norm(s["codigo"]): s["capacidad"] for s in salones}
    assert len(salones) == len(OFICIALES), f"Quedaron {len(salones)} salones, se esperaban {len(OFICIALES)}"
    assert all(str(capacidades[c]) == str(plan["capacidades_oficiales"][c]) for c in OFICIALES), \
        "Las capacidades de los salones oficiales cambiaron"
    print(f"OK: {len(salones)} salones oficiales, capacidades intactas, "
          f"{len(movimientos)} clases reubicadas.")


def _clases_oficiales() -> int:
    ids = {int(s["id"]) for s in db.query("SELECT id,codigo FROM salones")
           if _norm(s["codigo"]) in OFICIALES}
    return sum(1 for a in db.query("SELECT salon_id FROM asignaciones_horario")
               if int(a["salon_id"]) in ids)


if __name__ == "__main__":
    main()
