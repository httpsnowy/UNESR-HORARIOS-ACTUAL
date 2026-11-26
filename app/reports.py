"""Generador de reportes HTML imprimibles.

Cambio solicitado: NO se muestra la 'Oferta Académica General de todas las
carreras'. El reporte se organize por CARRERA y dentro de ella por DÍA
(Lunes, Martes, Miércoles...), mostrando materias y profesores de ese día.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from . import db, queries

ESTILO = """
<style>
*{box-sizing:border-box}body{font-family:'Segoe UI',Arial,sans-serif;color:#0d1b2a;margin:0;padding:24px;font-size:12px}
.no-print{background:#0d1b2a;color:#fff;padding:14px 20px;border-radius:10px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:center}
.btn-print{background:#00e676;color:#0d1b2a;border:0;padding:9px 18px;font-weight:700;border-radius:6px;cursor:pointer}
.header{text-align:center;border-bottom:3px solid #0d1b2a;padding-bottom:12px;margin-bottom:22px}
.header h1{margin:0;font-size:19px;text-transform:uppercase}.header p{margin:3px 0;color:#455a64}
.sec-title{background:#152235;color:#fff;padding:9px 14px;font-weight:700;font-size:14px;border-left:5px solid #2196f3;margin:22px 0 12px;border-radius:4px}
.dia-title{background:#e3f2fd;color:#0d47a1;padding:7px 12px;font-weight:700;border-left:4px solid #2196f3;margin-top:14px}
table{width:100%;border-collapse:collapse;margin-bottom:16px}
th,td{border:1px solid #cfd8dc;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#eceff1;font-size:11px;text-transform:uppercase}
.vacio{color:#64748b;font-style:italic;padding:10px}
@media print{.no-print{display:none!important}body{padding:0}}
</style>
"""


def reporte_por_carrera(carrera_id: Optional[int] = None,
                        incluir_profesores: bool = False) -> str:
    carreras = queries.carreras_con_pensum()
    if carrera_id:
        carreras = [c for c in carreras if c["id"] == int(carrera_id)]
        if not carreras:
            carreras = []
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    total = sum(len(f) for c in carreras for f in queries.horario_por_carrera(c["id"]).values())

    html = [f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"]
    html.append(f"<title>UNESR — Horario por Carrera — {fecha}</title>{ESTILO}</head><body>")
    html.append("""<div class="no-print"><div><strong>UNESR · Núcleo Palo Verde</strong><br>
        <span style="font-size:11px;color:#b0bec5">Horario por carrera y día — usar "Guardar como PDF"</span></div>
        <button class="btn-print" onclick="window.print()">Imprimir / Guardar PDF</button></div>""")
    html.append(f"""<div class="header"><h1>Universidad Nacional Experimental Simón Rodríguez</h1>
        <p><strong>Horario de clases por carrera y día — Periodo 2026-2</strong></p>
        <p>Generado el {fecha} &bull; Clases: {total}</p></div>""")

    if not carreras:
        html.append('<p class="vacio">No hay carreras registradas o el filtro no coincide.</p>')

    for c in carreras:
        html.append(f'<div class="sec-title">{c["nombre"]} — {c["facultad"]}</div>')
        por_dia = queries.horario_por_carrera(c["id"])
        for dia, filas in por_dia.items():
            if not filas:
                continue
            html.append(f'<div class="dia-title">{dia} · {len(filas)} clase(s)</div>')
            html.append("""<table><thead><tr><th>Docente</th><th>Materia</th><th>Código</th>
                <th>Sección</th><th>Horario</th><th>Ambiente</th></tr></thead><tbody>""")
            for f in filas:
                html.append(
                    f"<tr><td><strong>{_esc(f['profesor'])}</strong></td><td>{_esc(f['materia'])}</td>"
                    f"<td>{_esc(f['codigo'])}</td><td>{_esc(f['seccion'])}</td>"
                    f"<td>{f['hora_inicio']}–{f['hora_fin']}</td><td>{_esc(f['ambiente'])}</td></tr>")
            html.append("</tbody></table>")

    if incluir_profesores:
        for p in queries.profesores():
            filas = queries.asignaciones_profesor(p["id"])
            if not filas:
                continue
            html.append(f'<div class="sec-title">Docente: {_esc(p["nombre"])}</div>')
            html.append("<table><thead><tr><th>Día</th><th>Materia</th><th>Carrera</th>"
                        "<th>Horario</th><th>Ambiente</th></tr></thead><tbody>")
            for f in sorted(filas, key=lambda x: (db.normalizar(x["dia"]), x["hora_inicio"])):
                html.append(f"<tr><td>{_esc(f['dia'])}</td><td>{_esc(f['materia'])}</td>"
                            f"<td>{_esc(f['carrera'])}</td><td>{f['hora_inicio']}–{f['hora_fin']}</td>"
                            f"<td>{_esc(f['ambiente'])}</td></tr>")
            html.append("</tbody></table>")

    html.append("</body></html>")
    return "".join(html)


def _esc(texto) -> str:
    from html import escape
    return escape(str(texto or ""))
