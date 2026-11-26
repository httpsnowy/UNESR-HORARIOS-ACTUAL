"""Pruebas automatizadas del sistema UNESR Horarios.

Cubren los requisitos corregidos:
  - pensum completo (sin el recorte a 12 materias),
  - horario por carrera y día (sin oferta general),
  - filtros válidos e inválidos,
  - asignación automática sin conflictos y preservando reasignaciones manuales,
  - carga y eliminación de datos,
  - rutas web.

Ejecutar:
    python -m unittest discover -s tests -v
    # o: python -m pytest tests -v
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="unesr_tests_"))
# La capa db.py lee la configuración al importarse: configurarla ANTES.
# Las pruebas son siempre locales, aunque el .env tenga credenciales de
# Supabase (DB_BACKEND=auto), para no depender de la red ni alterar datos reales.
os.environ["DB_BACKEND"] = "sqlite"
os.environ["DATABASE_PATH"] = str(TMP / "test.db")
shutil.copy2(ROOT / "data" / "universidad_horarios.db", os.environ["DATABASE_PATH"])

from app import (carga_multiple, constantes, db, importers, pdf_importers,  # noqa: E402
                 queries, reports, scheduler)
from app.web import app  # noqa: E402


class BaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls._plan = importers.importar_plan_estudio()
        cls._pnf = pdf_importers.importar_pnfs()
        cls._carreras = queries.carreras_con_pensum()
        cls._cliente = app.test_client()


class TestCargaMultipleYCuadro(BaseTest):
    NOMBRE_PRUEBA = "DOCENTE CARGA MULTIPLE PRUEBA"

    def _fila(self, indice, materia, dia, profesor=None):
        return {
            "indice": indice, "profesor": profesor or self.NOMBRE_PRUEBA,
            "cedula": "", "email": "", "carrera": self._carreras[0]["nombre"],
            "materia": materia, "codigo": "PRUEBA" + str(indice), "seccion": "Sección A",
            "semestre": "1er Semestre", "creditos": 3, "bloques": 1, "ambiente": "",
            "compartidos": False, "dias": [dia],
            "hora_inicio": "07:40", "hora_fin": "09:20",
        }

    def test_cuadro_horario_es_matriz_dia_hora(self):
        cid = self._carreras[0]["id"]
        cuadro = queries.cuadro_horario(cid)
        self.assertEqual(cuadro["dias"][:6], db.DIAS_ORDEN[:6])
        self.assertTrue(all(d in db.DIAS_ORDEN for d in cuadro["dias"]))
        self.assertGreater(len(cuadro["franjas"]), 0)
        self.assertGreater(cuadro["total"], 0)
        ini, fin = cuadro["franjas"][0]
        self.assertLess(ini, fin)
        self.assertTrue(any(cuadro["celdas"][d].get(ini) for d in cuadro["dias"]))

    def test_carga_multiple_rechaza_conflicto_sin_guardar(self):
        antes = db.estadisticas()["profesores"]
        filas = [self._fila(1, "Materia A Prueba", "Lunes"),
                 self._fila(2, "Materia B Prueba", "Lunes")]
        errores = carga_multiple.validar_filas(filas)
        self.assertTrue(any("Conflicto" in e for e in errores), errores)
        self.assertEqual(db.estadisticas()["profesores"], antes)

    def test_carga_multiple_guarda_varias_materias_del_mismo_docente(self):
        filas = [self._fila(1, "Materia C Prueba", "Lunes"),
                 self._fila(2, "Materia D Prueba", "Martes")]
        self.assertEqual(carga_multiple.validar_filas(filas), [])
        res = carga_multiple.guardar_filas(filas)
        self.assertEqual(res["guardados"]["carga"], 2)
        pid = db.query("SELECT id FROM profesores WHERE nombre=?", (self.NOMBRE_PRUEBA,))[0]["id"]
        n = db.query("""SELECT COUNT(*) AS n FROM carga_academica ca JOIN materias m
                        ON m.id=ca.materia_id WHERE ca.profesor_id=? AND m.nombre LIKE '%Prueba'""",
                     (pid,))[0]["n"]
        self.assertGreaterEqual(n, 2)
        self.assertEqual(scheduler.conflictos(), [])

    def test_ruta_carga_multiple_y_html(self):
        r = self._cliente.post("/carga-multiple", data={
            "total_filas": "2",
            "profesor_0": self.NOMBRE_PRUEBA, "carrera_0": self._carreras[0]["nombre"],
            "materia_0": "Materia E Prueba", "dia_0": "Lunes",
            "hora_inicio_0": "07:40", "hora_fin_0": "09:20",
            "profesor_1": self.NOMBRE_PRUEBA, "carrera_1": self._carreras[0]["nombre"],
            "materia_1": "Materia F Prueba", "dia_1": "Martes",
            "hora_inicio_1": "07:40", "hora_fin_1": "09:20",
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        html = self._cliente.get("/nueva-carga").data
        self.assertIn(b"agregar-fila", html)
        self.assertIn("Guardar carga múltiple".encode(), html)
        doc = self._cliente.get("/docentes").data
        self.assertIn(b"buscar-docente", doc)
        self.assertIn(b"filtro-condicion", doc)
        hor = self._cliente.get(f"/horarios?carrera_id={self._carreras[0]['id']}").data
        self.assertIn(b"cuadro", hor)
        self.assertNotIn(b"Todas las carreras", hor)


class TestCondicionesYPnf(BaseTest):
    """Condición del docente y pensum PNF sin fichas docentes."""

    def test_condiciones_canonicas_del_documento(self):
        for valor in ("Contratado Nuevo", "Contratado Anterior", "Ordinario",
                      "Instructor", "Asociado", "Exclusiva", "Tiempo Completo"):
            self.assertIn(valor, constantes.CONDICIONES_DOCENTE)

    def test_condicion_se_guarda_en_ficha_individual(self):
        nombre = "DOCENTE CONDICION INDIVIDUAL"
        r = self._cliente.post("/nueva-carga", data={
            "profesor": nombre, "carrera": self._carreras[0]["nombre"],
            "materia": "Materia Condicion Individual", "dia": "Miercoles",
            "hora_inicio": "07:40", "hora_fin": "09:20",
            "condicion": "Ordinario",
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        fila = db.query("SELECT condicion FROM profesores WHERE nombre = ?", (nombre,))[0]
        self.assertEqual(fila["condicion"], "Ordinario")

    def test_condicion_se_guarda_en_carga_multiple(self):
        nombre = "DOCENTE CONDICION MULTIPLE"
        r = self._cliente.post("/carga-multiple", data={
            "total_filas": "1",
            "profesor_0": nombre, "carrera_0": self._carreras[0]["nombre"],
            "materia_0": "Materia Condicion Multiple", "dia_0": "Jueves",
            "hora_inicio_0": "07:40", "hora_fin_0": "09:20",
            "condicion_0": "Contratado Anterior",
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        fila = db.query("SELECT condicion FROM profesores WHERE nombre = ?", (nombre,))[0]
        self.assertEqual(fila["condicion"], "Contratado Anterior")

    def test_formularios_ofrecen_condiciones(self):
        html = self._cliente.get("/nueva-carga").data.decode()
        self.assertIn('name="condicion"', html)
        self.assertIn('data-campo="condicion"', html)
        self.assertIn("Contratado Nuevo", html)
        doc = self._cliente.get("/docentes").data.decode()
        self.assertIn("Contratado Nuevo", doc)

    def test_materias_del_formulario_se_filtran_por_carrera(self):
        opciones = queries.opciones_carga()
        mapa = opciones["materias_por_carrera"]
        for carrera in self._carreras:
            catalogo = {m["nombre"] for m in db.query(
                "SELECT nombre FROM materias WHERE carrera_id = ?", (carrera["id"],))}
            pensum = {m["nombre"] for m in carrera["materias"]}
            self.assertTrue(set(mapa[carrera["nombre"]]).issubset(catalogo | pensum),
                            carrera["nombre"])
        self.assertLess(len(mapa["PNF Agroecología"]), len(opciones["materias"]))
        html = self._cliente.get("/nueva-carga").data.decode()
        self.assertIn("MATERIAS_POR_CARRERA", html)
        self.assertIn("enlazarMaterias", html)

    def test_pnf_tiene_pensum_pero_no_clases_y_lo_explica(self):
        for carrera in self._carreras:
            if not carrera["nombre"].startswith("PNF "):
                continue
            estado = queries.estado_carga_carrera(carrera["id"])
            self.assertGreater(estado["materias_pensum"], 0, carrera["nombre"])
            self.assertEqual(estado["asignaciones"], 0, carrera["nombre"])
            self.assertTrue(estado["sin_clases"], carrera["nombre"])
            self.assertEqual(len(estado["pendientes"]), estado["materias_pensum"])
            html = self._cliente.get(
                f"/horarios?carrera_id={carrera['id']}").data.decode()
            self.assertIn("El pensum sí está cargado", html)
            self.assertIn("pendientes de asignar", html)
            self.assertNotIn("Esta carrera aún no tiene clases asignadas", html)


class TestDatosYPlan(BaseTest):
    def test_semilla_tiene_datos_reales(self):
        s = db.estadisticas()
        self.assertGreaterEqual(s["carreras"], 9)
        self.assertGreaterEqual(s["profesores"], 100)
        self.assertEqual(s["salones"], 41)

    def test_plan_estudio_importado_completo(self):
        self.assertGreaterEqual(self._plan["total"], 650)
        self.assertGreaterEqual(db.estadisticas()["planes_estudio"], 620)

    def test_todas_las_carreras_muestran_pensum_sin_recorte(self):
        self.assertEqual(len(self._carreras), 12)
        for c in self._carreras:
            self.assertGreater(len(c["materias"]), 12,
                               f"{c['nombre']} sigue recortado a 12 materias")
        self.assertEqual(self._carreras[0]["fuente"], "Plan de estudio 2024")

    def test_los_tres_pnf_se_cargan_desde_pdf(self):
        self.assertGreaterEqual(self._pnf["fisioterapia"], 40)
        self.assertGreaterEqual(self._pnf["veterinaria"], 45)
        self.assertGreaterEqual(self._pnf["agroecologia"], 40)
        nombres = {c["nombre"] for c in self._carreras}
        self.assertTrue({"PNF Fisioterapia", "PNF Veterinaria", "PNF Agroecología"} <= nombres)

    def test_recarga_de_pnf_es_idempotente(self):
        antes = db.estadisticas()["planes_estudio"]
        pdf_importers.importar_pnfs()
        self.assertEqual(db.estadisticas()["planes_estudio"], antes)


class TestHorariosYFiltros(BaseTest):
    def test_horario_por_carrera_esta_agrupado_por_dia(self):
        carrera = next(c for c in self._carreras if c["nombre"].startswith("Administración"))
        por_dia = queries.horario_por_carrera(carrera["id"])
        self.assertEqual(list(por_dia.keys()), db.DIAS_ORDEN)
        total = sum(len(v) for v in por_dia.values())
        self.assertGreater(total, 0)
        # Ninguna fila de otro día se cuela en Lunes
        lunes = por_dia["Lunes"]
        self.assertTrue(all(db.normalizar(f["dia"]) == "LUNES" for f in lunes))

    def test_filtro_por_carrera_y_dia(self):
        carrera = self._carreras[0]
        filas = queries.oferta(carrera_id=carrera["id"], dia="Lunes")
        self.assertTrue(filas)
        self.assertTrue(all(f["carrera_id"] == carrera["id"] for f in filas))
        self.assertTrue(all(db.normalizar(f["dia"]) == "LUNES" for f in filas))

    def test_reporte_no_incluye_oferta_general(self):
        html = reports.reporte_por_carrera(self._carreras[0]["id"])
        self.assertIn("Lunes", html)
        self.assertNotIn("OFERTA ACADÉMICA GENERAL", html)
        self.assertIn(self._carreras[0]["nombre"], html)


class TestAsignador(BaseTest):
    def test_generar_asignaciones_sin_conflictos(self):
        resultado = scheduler.generar_horarios_automaticos()
        self.assertGreater(resultado["asignados"], 400,
                           f"El asignador solo dejó {resultado['asignados']} clases")
        self.assertEqual(scheduler.conflictos(), [])

    def test_reasignacion_manual_sobrevive_a_la_regeneracion(self):
        a = db.query("SELECT id,salon_id,dia,hora_inicio,hora_fin FROM asignaciones_horario LIMIT 1")[0]
        otro = db.query("SELECT id FROM salones WHERE id != ? LIMIT 1", (a["salon_id"],))[0]
        db.execute("""UPDATE asignaciones_horario SET salon_id=?, estado='Manual' WHERE id=?""",
                   (otro["id"], a["id"]))
        scheduler.generar_horarios_automaticos()
        actual = db.query("SELECT salon_id,estado FROM asignaciones_horario WHERE id=?", (a["id"],))
        self.assertEqual(actual[0]["estado"], "Manual")
        self.assertEqual(actual[0]["salon_id"], otro["id"])

    def test_valida_choque_de_docente(self):
        a = db.query("SELECT * FROM asignaciones_horario LIMIT 1")[0]
        ok, msg = scheduler.validar_cambio_manual(
            a["id"], a["salon_id"], a["dia"], a["hora_inicio"], a["hora_fin"])
        # El mismo ambiente/horario es el propio registro: debe pasar (se excluye id).
        self.assertTrue(ok, msg)


class TestRutasWeb(BaseTest):
    def test_rutas_principales(self):
        for url in ("/", "/horarios", "/carreras", "/ambientes", "/docentes",
                    "/nueva-carga", "/api/estadisticas"):
            with self.subTest(url=url):
                self.assertEqual(self._cliente.get(url).status_code, 200)

    def test_filtro_por_carrera_en_la_web(self):
        cid = self._carreras[0]["id"]
        r = self._cliente.get(f"/horarios?carrera_id={cid}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b"OFERTA ACAD\xc3\x89MICA GENERAL", r.data)

    def test_api_horario_y_validacion_de_id(self):
        cid = self._carreras[0]["id"]
        r = self._cliente.get(f"/api/carreras/{cid}/horario")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.get_json()).intersection(db.DIAS_ORDEN), set(db.DIAS_ORDEN))
        self.assertEqual(self._cliente.get("/api/carreras/999999/horario").status_code, 404)

    def test_ruta_cargar_pnfs(self):
        r = self._cliente.post("/cargar-pnfs", follow_redirects=False)
        self.assertEqual(r.status_code, 302)

    def test_reporte_imprimible(self):
        r = self._cliente.get("/reporte?descargar=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Lunes", r.data)


# El prefijo ZZ garantiza que el vaciado se ejecute DESPUÉS del resto de pruebas.
class TestZZ_CargaYEliminacion(BaseTest):
    def test_alta_y_borrado_de_docente(self):
        nombre = "DOCENTE PRUEBA AUTOMATIZADA"
        pid = db.get_or_create("profesores", "nombre", nombre)
        self.assertGreater(pid, 0)
        self.assertTrue(db.query("SELECT id FROM profesores WHERE nombre=?", (nombre,)))
        db.execute("DELETE FROM profesores WHERE id=?", (pid,))
        self.assertFalse(db.query("SELECT id FROM profesores WHERE nombre=?", (nombre,)))

    def test_z_vaciar_solo_limpia_clases_y_conserva_catalogos(self):
        # Se ejecuta al final para no afectar a las demás pruebas.
        antes = db.estadisticas()
        db.limpiar_carga_academica()
        s = db.estadisticas()
        self.assertEqual(s["clases_programadas"], 0)
        for catalogo in ("salones", "carreras", "profesores", "materias"):
            self.assertEqual(s[catalogo], antes[catalogo], catalogo)
        self.assertGreater(len(db.query("SELECT id FROM planes_estudio LIMIT 1")), 0)
        self.assertEqual(db.query("SELECT id FROM carga_academica LIMIT 1"), [])
        self.assertEqual(db.query("SELECT id FROM disponibilidades LIMIT 1"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
