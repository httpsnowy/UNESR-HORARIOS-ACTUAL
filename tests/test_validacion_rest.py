"""Pruebas sin red del traductor PostgREST y de la normalización de campos."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DB_BACKEND", "sqlite")

from app import db, scheduler  # noqa: E402


class TestNormalizacionCampos(unittest.TestCase):
    def test_enteros_reales_y_valores_por_defecto(self):
        self.assertEqual(db.normalizar_entero("3"), 3)
        self.assertEqual(db.normalizar_entero(3.0), 3)
        self.assertEqual(db.normalizar_entero("", default=45), 45)
        self.assertEqual(db.normalizar_entero(None, default=1), 1)

    def test_enteros_rechazan_texto_decimales_y_exponentes(self):
        for valor in ("3.5", "1e3", "3 créditos", "abc", "V-1234567", -1, 3.7, True):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                db.normalizar_entero(valor)
        with self.assertRaises(ValueError):
            db.normalizar_entero("8", minimo=1, maximo=7)

    def test_cedulas_se_canonicalizan(self):
        casos = {
            "V-1234567": "V-1234567",
            "v 3.176.617": "V-3176617",
            "V-19.650.607": "V-19650607",
            "E12345678": "E-12345678",
            "": "",
            None: "",
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(db.normalizar_cedula(entrada), esperado)

    def test_cedulas_invalidas_se_rechazan(self):
        for valor in ("1234567", "X-1234567", "V-123", "V-1.2.3", "V-123456789"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                db.normalizar_cedula(valor)


class TestRestQuery(unittest.TestCase):
    def test_distinct_y_as_se_normalizan_sin_enviar_sql_a_postgrest(self):
        vistos = []

        def falso_rest(tabla, method="GET", params=None, **kwargs):
            vistos.append((tabla, dict(params or {})))
            if " AS " in str(params):
                raise AssertionError("AS llegó a PostgREST")
            return [{"codigo": "A"}, {"codigo": "A"}, {"codigo": "B"}]

        with patch.object(db, "_rest", side_effect=falso_rest):
            filas = db._rest_query(
                "SELECT DISTINCT codigo FROM materias WHERE codigo!='' ORDER BY codigo", ())

        self.assertEqual([f["codigo"] for f in filas], ["A", "B"])
        parametros = vistos[0][1]
        self.assertEqual(parametros["select"], "codigo")
        self.assertIn("neq.", parametros["codigo"])
        self.assertEqual(parametros["order"], "codigo.asc")

    def test_alias_as_se_devuelve_en_python(self):
        vistos = []

        def falso_rest(tabla, method="GET", params=None, **kwargs):
            vistos.append(dict(params or {}))
            return [{"carrera_id": 1, "codigo": "X", "nombre": "N",
                     "semestre": "1er Semestre", "unidad_credito": 3}]

        sql = ("SELECT carrera_id, codigo, nombre, semestre AS ciclo, unidad_credito "
               "FROM materias ORDER BY semestre, nombre")
        with patch.object(db, "_rest", side_effect=falso_rest):
            filas = db._rest_query(sql, ())
        self.assertEqual(filas[0]["ciclo"], "1er Semestre")
        self.assertEqual(filas[0]["semestre"], "1er Semestre")
        self.assertNotIn(" AS ", vistos[0]["select"])
        self.assertEqual(vistos[0]["order"], "semestre.asc,nombre.asc")

    def test_count_exacto_usa_content_range(self):
        def falso_rest(tabla, method="GET", params=None, **kwargs):
            return [], {"content-range": "0-0/12"}

        with patch.object(db, "_rest", side_effect=falso_rest):
            self.assertEqual(db._rest_query("SELECT COUNT(*) n FROM carreras", ()),
                             [{"n": 12}])

    def test_count_con_join_y_subconsulta_van_a_fallback(self):
        sqls = [
            ("SELECT COUNT(*) AS n FROM carga_academica ca JOIN materias m "
             "ON m.id=ca.materia_id WHERE ca.profesor_id=?", (1,)),
            ("SELECT s.*, (SELECT COUNT(*) FROM asignaciones_horario a "
             "WHERE a.salon_id=s.id) AS usos FROM salones s ORDER BY s.codigo", ()),
            ("SELECT COUNT(DISTINCT salon_id) n FROM asignaciones_horario", ()),
        ]
        for sql, params in sqls:
            with self.subTest(sql=sql[:40]), self.assertRaises(db.DatabaseError):
                db._rest_query(sql, params)

    def test_where_sin_espacios_y_literales_se_traducen(self):
        vistos = []

        def falso_rest(tabla, method="GET", params=None, **kwargs):
            vistos.append(dict(params or {}))
            return []

        with patch.object(db, "_rest", side_effect=falso_rest):
            db._rest_query("SELECT id FROM carreras WHERE nombre=? LIMIT 1", ("Derecho",))
            db._rest_query("SELECT id FROM asignaciones_horario WHERE estado='Manual'", ())
        self.assertEqual(vistos[0]["nombre"], "eq.Derecho")
        self.assertEqual(vistos[0]["limit"], 1)
        self.assertEqual(vistos[1]["estado"], "eq.Manual")

    def test_condicion_no_traducida_nunca_se_ignora(self):
        with patch.object(db, "_rest", return_value=[]):
            for sql in ("SELECT id FROM salones WHERE codigo LIKE ?",
                        "SELECT id FROM carreras WHERE id=?"):
                with self.subTest(sql=sql), self.assertRaises(db.DatabaseError):
                    db._rest_query(sql, ())


class TestDetalleConflictos(unittest.TestCase):
    def test_conflictos_incluyen_motivo_legible_y_sugerencia(self):
        base = {
            "dia": "Lunes", "hora_inicio": "07:40", "hora_fin": "09:20",
            "salon_id": 10, "ambiente": "P1-01", "carrera_id": 1,
            "carrera": "Derecho", "seccion": "101", "dia_fijo": None,
        }
        a = dict(base, id=1, profesor_id=1, profesor="DOCENTE A",
                 materia="Materia A", estado="Auto")
        b = dict(base, id=2, profesor_id=2, profesor="DOCENTE B",
                 materia="Materia B", estado="Manual")
        with patch.object(scheduler.db, "query", return_value=[a, b]):
            cols = scheduler.conflictos()
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["motivo"], "ambiente")
        self.assertEqual(cols[0]["ids"], [1, 2])
        self.assertEqual(cols[0]["desde"], "07:40")
        self.assertEqual(cols[0]["sugerencia"], "manual")
        self.assertIn("Materia A", cols[0]["detalle"])
        self.assertIn("Materia B", cols[0]["detalle"])


class TestOrdenAmbientes(unittest.TestCase):
    def test_categorias_oficiales(self):
        casos = {
            "P1-01": "Piso 1", "P2-09": "Piso 2", "P3-23": "Piso 3",
            "P4-28": "Piso 4", "AULA 305": "Piso 3", "MAGNA": "Piso 3",
            "SATELITAL-01": "Satelitales", "PB-00": "Planta Baja (PB)",
            "PLANTA BAJA 2": "Planta Baja (PB)", "VIRTUAL-01": "Virtuales",
            "CURSO VIRTUAL": "Virtuales", "ONLINE-02": "Virtuales",
            "CANCHA": "Laboratorios y Otros",
            "COORDINACIÒN MATEMÁTICA": "Laboratorios y Otros",
            "´P4-10": "Piso 4",
        }
        for codigo, sector in casos.items():
            with self.subTest(codigo=codigo):
                self.assertEqual(db.categoria_ambiente(codigo)[0], sector)

    def test_inventario_oficial_es_el_correcto(self):
        esperado = ([f"P1-{n:02d}" for n in range(1, 9)]
                    + [f"P2-{n:02d}" for n in range(9, 23)]
                    + [f"P3-{n:02d}" for n in range(23, 28)]
                    + [f"P4-{n:02d}" for n in range(28, 38)]
                    + ["SATELITAL-01", "SATELITAL-02", "VIRTUAL-01", "VIRTUAL-02"])
        self.assertEqual(list(db.AMBIENTES_OFICIALES), esperado)
        self.assertEqual(len(db.AMBIENTES_OFICIALES), 41)

        filas = [{"id": i, "codigo": c} for i, c in enumerate(
            ["VIRTUAL-01", "P3-04", "PB-01", "P2-09", "P1-01", "CURSO VIRTUAL"])]
        self.assertEqual(
            [f["codigo"] for f in db.ambientes_oficiales(filas)],
            ["P1-01", "P2-09", "VIRTUAL-01"],
        )

    def test_orden_natural_y_continuo_por_pisos(self):
        codigos = ["VIRTUAL-01", "P3-04", "P1-10", "SATELITAL-01", "PB-02",
                   "P2-09", "COORDINACIÓN PASANTIAS", "P1-02", "P4-28", "P3-23"]
        filas = [{"id": i, "codigo": c} for i, c in enumerate(codigos)]
        ordenados = db.ordenar_ambientes(filas)
        self.assertEqual([f["codigo"] for f in ordenados], [
            "P1-02", "P1-10", "P2-09", "P3-04", "P3-23", "P4-28",
            "SATELITAL-01", "PB-02", "VIRTUAL-01", "COORDINACIÓN PASANTIAS",
        ])
        self.assertEqual([g["sector"] for g in db.agrupar_ambientes(filas)], [
            "Piso 1", "Piso 2", "Piso 3", "Piso 4",
            "Satelitales", "Planta Baja (PB)", "Virtuales", "Laboratorios y Otros",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
