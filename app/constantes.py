"""Valores canónicos del registro docente (Oferta Académica 2026-2).

Fuente: ``uploads/oferta_acad_mica_completa_2026_2.txt``, sección VII:
  * Campo 08 — Condición de Contratación
  * Campo 10 — Categoría Docente
  * Campo 11 — Dedicación
Además, sección V — Formatos "F": jubilados, asignaciones especiales,
honorarios/colaboradores y desincorporados.

Se exponen en un ``datalist`` (no en un ``select`` cerrado) para que el
usuario pueda elegir una de estas opciones o escribir un valor nuevo sin
necesitar migrar el esquema.
"""
from __future__ import annotations

# Campo 08 del documento original.
CONDICION_CONTRATACION = (
    "Contratado Nuevo",
    "Contratado Anterior",
    "Ordinario",
)

# Campo 10 del documento original.
CATEGORIA_DOCENTE = (
    "Instructor",
    "Asistente",
    "Agregado",
    "Asociado",
    "Titular",
)

# Campo 11 del documento original.
DEDICACION = (
    "Exclusiva",
    "Tiempo Completo",
    "Medio Tiempo",
    "Tiempo Convencional",
)

# Sección V del documento original + valor histórico ya presente en la BD.
SITUACION_ESPECIAL = (
    "Contratado/a",
    "Jubilado/a",
    "Asignación Especial",
    "Honorario/a",
    "Colaborador/a",
    "Desincorporado/a",
)


def _unicos(*grupos):
    vistos, salida = set(), []
    for grupo in grupos:
        for valor in grupo:
            clave = valor.casefold()
            if clave not in vistos:
                vistos.add(clave)
                salida.append(valor)
    return tuple(salida)


#: Opciones sugeridas para el campo ``condicion`` de ``profesores``.
CONDICIONES_DOCENTE = _unicos(
    CONDICION_CONTRATACION,
    SITUACION_ESPECIAL,
    CATEGORIA_DOCENTE,
    DEDICACION,
)
