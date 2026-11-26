"""Aplicación Flask: API + vistas web con bloqueos configurables y vaciado por carrera."""
from __future__ import annotations

import io
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.utils import secure_filename

from . import (carga_multiple, constantes, db, importers, pdf_importers,
               queries, reports, scheduler)

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = db.DATA_DIR.parent / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder=None)
app.secret_key = db.configuracion().get("FLASK_SECRET_KEY", "unesr_horarios_clave_local")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.config["MAX_FORM_PARTS"] = 20000
app.config["MAX_FORM_MEMORY_SIZE"] = 10 * 1024 * 1024
try:
    from werkzeug.wrappers import Request as _WzRequest
    _WzRequest.max_form_parts = 20000
    _WzRequest.max_form_memory_size = 10 * 1024 * 1024
except Exception:
    pass

_auto_reparacion_lock = threading.Lock()
_auto_reparado_en_arranque = False


def _reparar_bd_completa(forzar_plan: bool = False) -> Dict[str, int]:
    resumen = {
        "carreras_fusionadas": 0,
        "carreras_vacias_eliminadas": 0,
        "materias_fusionadas": 0,
        "pensum_plan_restaurado": 0,
        "pensum_backup_restaurado": 0,
        "pensum_pnf_restaurado": 0,
    }
    if forzar_plan or queries.detectar_carreras_duplicadas() > 0 or queries.carreras_sin_pensum():
        r_san = db.sanear_carreras_duplicadas()
        resumen["carreras_fusionadas"] = int(r_san.get("carreras_fusionadas", 0))
        resumen["carreras_vacias_eliminadas"] = int(r_san.get("carreras_vacias_eliminadas", 0))
        resumen["materias_fusionadas"] = int(r_san.get("materias_fusionadas", 0))

    necesita_plan = forzar_plan
    if not necesita_plan:
        carreras_plan_nombres = set(importers.MAPA_PLAN_CARRERA.values())
        actuales = {c["nombre"]: c for c in queries.carreras_con_pensum()}
        for nom in carreras_plan_nombres:
            c = actuales.get(nom)
            if not c or len(c["materias"]) == 0:
                necesita_plan = True
                break
            cid = int(c["id"])
            filas_p = db.query("SELECT id FROM planes_estudio WHERE carrera_id=?", (cid,))
            if not filas_p:
                necesita_plan = True
                break

    if necesita_plan and importers.encontrar_plan_estudio() is not None:
        try:
            rp = importers.importar_plan_estudio()
            resumen["pensum_plan_restaurado"] = int(rp.get("total", 0))
        except Exception:
            pass

    pnfs_esperados = ("PNF Fisioterapia", "PNF Veterinaria", "PNF Agroecología")
    actuales_post = {c["nombre"]: c for c in queries.carreras_con_pensum()}
    falta_pnf = any(
        (nom not in actuales_post) or len(actuales_post[nom]["materias"]) == 0
        for nom in pnfs_esperados
    )
    if forzar_plan or falta_pnf:
        try:
            resumen["pensum_backup_restaurado"] = db.recuperar_pensum_desde_respaldos_locales()
        except Exception:
            pass
        actuales_post2 = {c["nombre"]: c for c in queries.carreras_con_pensum()}
        sigue_faltando_pnf = any(
            (nom not in actuales_post2) or len(actuales_post2[nom]["materias"]) == 0
            for nom in pnfs_esperados
        )
        if sigue_faltando_pnf:
            try:
                rpnf = pdf_importers.importar_pnfs(ruta_uploads=UPLOADS)
                resumen["pensum_pnf_restaurado"] = sum(int(v or 0) for v in rpnf.values())
            except Exception:
                pass

    if queries.detectar_carreras_duplicadas() > 0:
        r_san2 = db.sanear_carreras_duplicadas()
        resumen["carreras_fusionadas"] += int(r_san2.get("carreras_fusionadas", 0))
        resumen["materias_fusionadas"] += int(r_san2.get("materias_fusionadas", 0))

    return resumen


@app.before_request
def _init():
    global _auto_reparado_en_arranque
    db.init_db()
    if not _auto_reparado_en_arranque:
        with _auto_reparacion_lock:
            if not _auto_reparado_en_arranque:
                _auto_reparado_en_arranque = True
                try:
                    _reparar_bd_completa(forzar_plan=False)
                except Exception:
                    pass


@app.context_processor
def _globales():
    return {
        "profesores_global": queries.profesores(),
        "carreras_global": [{"id": c["id"], "nombre": c["nombre"]} for c in queries.carreras_con_pensum()],
        "backend": db.backend_activo(),
        "dias_form": carga_multiple.DIAS_FORM,
        "condiciones_docente": constantes.CONDICIONES_DOCENTE,
    }


@app.route("/logo.png")
def logo():
    return send_file(db.RECURSOS / "assets" / "UNESR.png", mimetype="image/png")


@app.route("/")
def index():
    stats = db.estadisticas()
    conflictos = scheduler.conflictos()
    stats["conflictos"] = len(conflictos)
    return render_template("index.html", stats=stats, conf=None,
                           conflictos=conflictos)


@app.route("/dashboard")
def dashboard():
    return redirect(url_for("index"))


# ── Nueva carga ────────────────────────────────────────────────────────
@app.route("/nueva-carga", methods=["GET", "POST"])
def nueva_carga():
    opciones = queries.opciones_carga()
    bloques_defecto: List[Dict] = []
    if request.method == "POST":
        datos = request.form
        errores: List[str] = []
        nombre = (datos.get("profesor") or "").strip()
        materia = (datos.get("materia") or "").strip()
        carrera = (datos.get("carrera") or "").strip()
        ambiente = (datos.get("ambiente") or "").strip().upper()
        compartidos = bool(datos.get("compartidos"))
        horarios = carga_multiple.extraer_bloques_formulario(datos)
        if not nombre:
            errores.append("El nombre del docente es obligatorio.")
        if not materia:
            errores.append("La materia es obligatoria.")
        err_car = carga_multiple.validar_carrera_catalogo(carrera)
        if err_car:
            errores.append(err_car)

        slots, errs_h = carga_multiple.expandir_slots(horarios)
        errores.extend(errs_h)

        cedula = ""
        creditos = 0
        bloques = len(slots) if slots else 1
        try:
            cedula = db.normalizar_cedula(datos.get("cedula"))
            creditos = db.normalizar_entero(datos.get("creditos"), minimo=0, maximo=30, default=0)
        except ValueError as exc:
            errores.append(str(exc))

        if not errores and slots:
            err_lim = carga_multiple.validar_limite_horas(
                carrera,
                materia,
                slots,
                creditos=creditos,
                horas_materia_form=datos.get("horas_materia"),
            )
            if err_lim:
                errores.append(err_lim)

        if not errores and slots:
            errores.extend(carga_multiple.validar_contra_bloqueos(nombre, ambiente, slots))

        if not errores and slots:
            manuales = db.query("SELECT * FROM asignaciones_horario WHERE estado='Manual'")
            prof_map = {db.normalizar(p["nombre"]): int(p["id"]) for p in db.query("SELECT id,nombre FROM profesores")}
            salon_map = {str(s["codigo"]).upper(): int(s["id"]) for s in db.query("SELECT id,codigo FROM salones")}
            pid_exist = prof_map.get(db.normalizar(nombre))
            sid_exist = salon_map.get(ambiente)
            for dia, ini, fin in slots:
                for a in manuales:
                    if db.normalizar(dia) != db.normalizar(a["dia"]):
                        continue
                    if not carga_multiple._solapan((ini, fin), (a["hora_inicio"], a["hora_fin"])):
                        continue
                    if pid_exist is not None and int(a["profesor_id"]) == pid_exist and not compartidos:
                        errores.append(
                            f"Conflicto: {nombre} ya tiene una clase manual el {dia} "
                            f"{a['hora_inicio']}–{a['hora_fin']}."
                        )
                    if sid_exist is not None and int(a["salon_id"]) == sid_exist and not scheduler.es_compartible(ambiente):
                        errores.append(
                            f"Conflicto: el ambiente {ambiente} ya está ocupado manualmente el {dia} "
                            f"{a['hora_inicio']}–{a['hora_fin']}."
                        )

        if errores:
            for e in errores:
                flash(e, "danger")
            return render_template(
                "nueva_carga.html",
                opciones=opciones,
                form=datos,
                bloques_form=horarios or bloques_defecto,
                filas_multi=session.get("filas_multi", []),
                tab_activa="individual",
                limpiar_borrador_ind=False,
            )

        respaldo = db.respaldar_bd("antes_nueva_carga")
        try:
            prof_id = carga_multiple.buscar_o_crear_profesor(
                nombre,
                cedula=cedula,
                email=(datos.get("email") or "").strip(),
                condicion=(datos.get("condicion") or "").strip(),
            )
            car_id = carga_multiple.buscar_o_crear_carrera(carrera)
            mat_id = carga_multiple.buscar_o_crear_materia(
                materia,
                car_id,
                (datos.get("codigo") or "").strip(),
                (datos.get("semestre") or "").strip() or "1er Semestre",
                creditos,
            )
            cid, _ = carga_multiple.guardar_carga_y_bloques(
                prof_id=prof_id,
                mat_id=mat_id,
                seccion=(datos.get("seccion") or "").strip() or "Sección A",
                slots=slots,
                bloques_solicitados=bloques,
                ambiente=ambiente,
                compartidos=compartidos,
            )
            resultado = scheduler.generar_horarios_automaticos()
            propias = db.query(
                "SELECT dia,hora_inicio,hora_fin FROM asignaciones_horario WHERE carga_id=?",
                (cid,),
            )
            propias.sort(key=lambda r: (carga_multiple._orden_dia(r["dia"]), carga_multiple._a_minutos(r["hora_inicio"])))
            resumen = " · ".join(f"{r['dia']} {r['hora_inicio']}–{r['hora_fin']}" for r in propias)
            if len(propias) >= len(slots):
                flash(
                    f"Curso guardado: «{materia}» quedó programado en {len(propias)} bloque(s) "
                    f"({resumen}).",
                    "success",
                )
            else:
                flash(
                    f"Curso guardado parcialmente: «{materia}» solo pudo asignar {len(propias)} de "
                    f"{len(slots)} bloque(s) solicitados." + (f" ({resumen})" if resumen else ""),
                    "warning",
                )
                for d in resultado.get("detalles", []):
                    if d.get("carga_id") == cid:
                        flash(d["detalle"], "warning")
            session["limpiar_borrador_ind"] = True
            return redirect(url_for("horarios", carrera_id=car_id))
        except Exception as exc:
            db.restaurar_bd(respaldo)
            flash(f"Error al guardar (se restauró el estado anterior): {exc}", "danger")
            return render_template(
                "nueva_carga.html",
                opciones=opciones,
                form=datos,
                bloques_form=horarios or bloques_defecto,
                filas_multi=session.get("filas_multi", []),
                tab_activa="individual",
                limpiar_borrador_ind=False,
            )

    filas_multi = session.pop("filas_multi", [])
    limpiar_ind = bool(session.pop("limpiar_borrador_ind", False))
    return render_template(
        "nueva_carga.html",
        opciones=opciones,
        form={},
        bloques_form=bloques_defecto,
        filas_multi=filas_multi,
        tab_activa="multiple" if filas_multi else "individual",
        limpiar_borrador_ind=limpiar_ind,
    )


@app.route("/api/carga-multiple", methods=["POST"])
def api_carga_multiple():
    payload = request.get_json(silent=True) or {}
    filas_raw = payload.get("filas") or []
    solo_validas = bool(payload.get("solo_validas"))
    filas = carga_multiple.parsear_filas_json(filas_raw)
    errores, por_fila = carga_multiple.validar_filas_detallado(filas)

    if errores and not solo_validas:
        return jsonify({
            "ok": False,
            "errores": errores,
            "errores_por_fila": {str(k): v for k, v in por_fila.items()},
            "total_filas": len(filas),
            "validas": len([f for f in filas if f["indice"] not in por_fila]),
            "con_error": len(por_fila),
        }), 400

    filas_a_guardar = [f for f in filas if f["indice"] not in por_fila] if solo_validas else filas
    filas_restantes_ui = [f["indice_ui"] for f in filas if f["indice"] in por_fila] if solo_validas else []

    if not filas_a_guardar:
        return jsonify({
            "ok": False,
            "errores": errores or ["No hay materias válidas para guardar."],
            "errores_por_fila": {str(k): v for k, v in por_fila.items()},
            "total_filas": len(filas),
            "validas": 0,
            "con_error": len(por_fila),
        }), 400

    if solo_validas:
        errs_sub, por_sub = carga_multiple.validar_filas_detallado(filas_a_guardar)
        if errs_sub:
            return jsonify({
                "ok": False,
                "errores": errs_sub,
                "errores_por_fila": {str(k): v for k, v in por_sub.items()},
                "total_filas": len(filas),
                "validas": 0,
                "con_error": len(por_sub),
            }), 400

    try:
        res = carga_multiple.guardar_filas(filas_a_guardar)
        g = res["guardados"]
        asig = res["asignacion"]
        carga_ids = res.get("carga_ids", [])
        asignadas_nuevas = 0
        solicitadas_nuevas = sum(len(f.get("slots", [])) for f in filas_a_guardar)
        for cid in carga_ids:
            asignadas_nuevas += len(
                db.query("SELECT id FROM asignaciones_horario WHERE carga_id=?", (cid,))
            )
        cids_set = set(carga_ids)
        advertencias = [d["detalle"] for d in asig.get("detalles", []) if d.get("carga_id") in cids_set][:12]
        carreras_ids = res.get("carreras_ids", [])
        destino = url_for("horarios", carrera_id=carreras_ids[0]) if carreras_ids else url_for("horarios")
        msg = (
            f"Carga múltiple guardada: {g['carga']} materia(s), "
            f"{asignadas_nuevas} de {solicitadas_nuevas} bloque(s) programados en el horario."
        )
        if not filas_restantes_ui:
            flash(msg, "success" if asignadas_nuevas >= solicitadas_nuevas else "warning")
            for adv in advertencias[:6]:
                flash(adv, "warning")
        return jsonify({
            "ok": True,
            "mensaje": msg,
            "guardadas": g["carga"],
            "asignadas": asignadas_nuevas,
            "solicitadas": solicitadas_nuevas,
            "advertencias": advertencias,
            "restantes_ui": filas_restantes_ui,
            "errores_restantes": errores if filas_restantes_ui else [],
            "redirect_url": destino,
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "errores": [f"Error al guardar la carga múltiple (sin cambios en BD): {exc}"],
            "errores_por_fila": {},
        }), 500


@app.route("/carga-multiple", methods=["POST"])
def carga_multiple_route():
    filas = carga_multiple.parsear_filas(request.form)
    errores = carga_multiple.validar_filas(filas)
    if errores:
        for e in errores[:10]:
            flash(e, "danger")
        if len(errores) > 10:
            flash(f"… y {len(errores) - 10} error(es) más.", "danger")
        if len(filas) <= 8:
            session["filas_multi"] = [
                {k: v for k, v in f.items() if k != "slots"} for f in filas
            ]
        return redirect(url_for("nueva_carga", _anchor="multiple"))

    try:
        res = carga_multiple.guardar_filas(filas)
        g = res["guardados"]
        asig = res["asignacion"]
        carga_ids = res.get("carga_ids", [])
        asignadas_nuevas = 0
        solicitadas_nuevas = sum(len(f.get("slots", [])) for f in filas)
        for cid in carga_ids:
            asignadas_nuevas += len(
                db.query("SELECT id FROM asignaciones_horario WHERE carga_id=?", (cid,))
            )
        cat = "success" if asignadas_nuevas >= solicitadas_nuevas else "warning"
        flash(
            f"Carga múltiple guardada: {g['carga']} materia(s), "
            f"{asignadas_nuevas} de {solicitadas_nuevas} bloque(s) programados en el horario.",
            cat,
        )
        cids_set = set(carga_ids)
        detalles_propios = [d["detalle"] for d in asig.get("detalles", []) if d.get("carga_id") in cids_set]
        for msg in detalles_propios[:8]:
            flash(msg, "warning")
        session.pop("filas_multi", None)
        carreras_ids = res.get("carreras_ids", [])
        if carreras_ids:
            return redirect(url_for("horarios", carrera_id=carreras_ids[0]))
        carrera = filas[0]["carrera"]
        fila_car = db.buscar_carrera_existente(carrera)
        if fila_car:
            return redirect(url_for("horarios", carrera_id=fila_car["id"]))
    except Exception as exc:
        flash(f"Error al guardar la carga múltiple (sin cambios en BD): {exc}", "danger")
        if len(filas) <= 8:
            session["filas_multi"] = [
                {k: v for k, v in f.items() if k != "slots"} for f in filas
            ]
    return redirect(url_for("nueva_carga", _anchor="multiple"))


@app.route("/importar", methods=["POST"])
def importar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Seleccione un archivo.", "danger")
        return redirect(url_for("nueva_carga"))
    nombre_seguro = secure_filename(archivo.filename)
    ext = Path(nombre_seguro).suffix.lower()
    if ext not in (".xlsx", ".txt", ".csv"):
        flash("Formato no soportado. Use .xlsx, .txt o .csv.", "danger")
        return redirect(url_for("nueva_carga"))
    destino = UPLOADS / nombre_seguro
    archivo.save(destino)
    try:
        resultado = importers.importar_oferta_excel(destino)
        if resultado.get("insertados", 0) > 0:
            scheduler.generar_horarios_automaticos()
            msg = f"Importadas {resultado['insertados']} filas de oferta académica."
            if resultado.get("omitidos"):
                msg += f" Se omitieron {resultado['omitidos']} fila(s) no válidas."
            flash(msg, "success")
            for adv in resultado.get("advertencias", [])[:5]:
                flash(adv, "warning")
            for err in resultado.get("errores", [])[:5]:
                flash(err, "warning")
            return redirect(url_for("horarios"))
        flash("No se importaron filas; la base de datos permanece intacta.", "warning")
    except Exception as exc:
        flash(f"Error al importar (la base de datos no fue alterada): {exc}", "danger")
    return redirect(url_for("nueva_carga"))


@app.route("/cargar-plan-estudio", methods=["POST"])
def cargar_plan():
    try:
        r = importers.importar_plan_estudio()
        flash(f"Plan de estudio cargado: {r['total']} materias en {len(r)-1} carreras.", "success")
    except Exception as exc:
        flash(f"Error al cargar el plan de estudio (sin daños en BD): {exc}", "danger")
    return redirect(url_for("carreras"))


@app.route("/cargar-pnfs", methods=["POST"])
def cargar_pnfs():
    try:
        r = pdf_importers.importar_pnfs(ruta_uploads=UPLOADS)
        total = sum(r.values())
        flash(f"PNF cargados: {total} materias "
              f"(Fisioterapia {r.get('fisioterapia', 0)}, "
              f"Veterinaria {r.get('veterinaria', 0)}, "
              f"Agroecología {r.get('agroecologia', 0)}).", "success")
    except Exception as exc:
        flash(f"Error al cargar los PNF (sin daños en BD): {exc}", "danger")
    return redirect(url_for("carreras"))


# ── Horarios ────────────────────────────────────────────────────────────
@app.route("/horarios")
def horarios():
    carrera_id = request.args.get("carrera_id", type=int)
    dia = request.args.get("dia") or None
    profesor_id = request.args.get("profesor_id", type=int)
    carreras = queries.carreras_con_pensum()
    if carrera_id and not any(c["id"] == carrera_id for c in carreras):
        flash("La carrera seleccionada no existe.", "warning")
        carrera_id = None
    filas = queries.oferta(carrera_id=carrera_id, dia=dia, profesor_id=profesor_id)
    por_dia = None
    cuadro = None
    estado = None
    carrera = None
    conflictos_por_id: Dict[int, str] = {}
    conflictos_carrera: List[Dict] = []
    for conflicto in scheduler.conflictos():
        for fila in (conflicto["a"], conflicto["b"]):
            cid = int(fila["id"])
            motivos = conflictos_por_id.setdefault(cid, set())
            motivos.add(conflicto["motivo"])
        if carrera_id and carrera_id in (conflicto.get("carrera_id"),
                                         conflicto.get("b_carrera_id")):
            conflictos_carrera.append(conflicto)
    conflictos_por_id = {cid: " y ".join(sorted(v))
                         for cid, v in conflictos_por_id.items()}
    if carrera_id:
        carrera = next(c for c in carreras if c["id"] == carrera_id)
        por_dia = queries.horario_por_carrera(carrera_id, dia=dia, profesor_id=profesor_id)
        cuadro = queries.cuadro_horario(carrera_id, dia=dia, profesor_id=profesor_id)
        estado = queries.estado_carga_carrera(carrera_id)
    return render_template("horarios.html", carreras=carreras, carrera_id=carrera_id,
                           carrera=carrera, dia=dia, profesor_id=profesor_id,
                           filas=filas, por_dia=por_dia, cuadro=cuadro, estado=estado,
                           profesores=queries.profesores(),
                           ambientes=db.ambientes_oficiales(
                               db.query("SELECT id,codigo FROM salones")),
                           conflictos_por_id=conflictos_por_id,
                           conflictos_carrera=conflictos_carrera,
                           bloqueos_activos=queries.obtener_bloqueos(solo_activos=True),
                           franjas=queries.obtener_franjas_sistema(),
                           dias=db.DIAS_ORDEN)


@app.route("/horarios/carrera/<int:carrera_id>/vaciar", methods=["POST"])
def vaciar_horario_carrera_route(carrera_id: int):
    """Elimina TODOS los bloques y cargas de UNA carrera/mención sin tocar las demás."""
    ok, msg = scheduler.eliminar_horarios_carrera(carrera_id)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("horarios", carrera_id=carrera_id))


@app.route("/oferta-general")
def oferta_general():
    return redirect(url_for("horarios"))


@app.route("/asignar-auto", methods=["POST"])
def asignar_auto():
    resultado = scheduler.generar_horarios_automaticos()
    flash(f"Asignación automática: {resultado['asignados']} clases; "
          f"{resultado['pendientes']} pendientes.", "success" if not resultado["pendientes"] else "warning")
    for m in resultado["mensajes"][:8]:
        if not m.startswith("OK"):
            flash(m, "info")
    for d in resultado.get("detalles", [])[:5]:
        flash(d["detalle"], "info")
    return redirect(request.referrer or url_for("horarios"))


@app.route("/reasignar/<int:aid>", methods=["POST"])
def reasignar(aid: int):
    try:
        salon_id = int(request.form["salon_id"])
        dia = request.form["dia"]
        ini, fin = request.form["hora_inicio"], request.form["hora_fin"]
        ok, msg = scheduler.editar_asignacion(aid, salon_id=salon_id, dia=dia, ini=ini, fin=fin)
        flash(msg, "success" if ok else "danger")
    except Exception as exc:
        flash(f"Datos inválidos: {exc}", "danger")
    return redirect(request.referrer or url_for("horarios"))


@app.route("/asignacion/<int:aid>/editar", methods=["POST"])
def editar_asignacion_route(aid: int):
    try:
        salon_id = int(request.form["salon_id"])
        dia = (request.form.get("dia") or "").strip()
        ini = (request.form.get("hora_inicio") or "").strip()
        fin = (request.form.get("hora_fin") or "").strip()
        prof_raw = (request.form.get("profesor_id") or "").strip()
        profesor_id = int(prof_raw) if prof_raw.isdigit() else None
        seccion = (request.form.get("seccion") or "").strip() or None
        compartido = bool(request.form.get("compartidos"))
        aplicar_toda = bool(request.form.get("aplicar_toda_materia"))
        ok, msg = scheduler.editar_asignacion(
            aid,
            salon_id=salon_id,
            dia=dia,
            ini=ini,
            fin=fin,
            profesor_id=profesor_id,
            seccion=seccion,
            compartido=compartido,
            aplicar_toda_materia=aplicar_toda,
        )
        flash(msg, "success" if ok else "danger")
    except Exception as exc:
        flash(f"Datos inválidos al editar el bloque: {exc}", "danger")
    return redirect(request.referrer or url_for("horarios"))


@app.route("/asignacion/<int:aid>/eliminar", methods=["POST"])
def eliminar_asignacion_route(aid: int):
    ok, msg, car_id = scheduler.eliminar_asignacion(aid)
    flash(msg, "success" if ok else "danger")
    return redirect(request.referrer or (url_for("horarios", carrera_id=car_id) if car_id else url_for("horarios")))


@app.route("/carga/<int:cid>/eliminar", methods=["POST"])
def eliminar_carga_route(cid: int):
    ok, msg, car_id = scheduler.eliminar_carga_completa(cid)
    flash(msg, "success" if ok else "danger")
    return redirect(request.referrer or (url_for("horarios", carrera_id=car_id) if car_id else url_for("horarios")))


# ── Ambientes ──────────────────────────────────────────────────────────
@app.route("/ambientes", methods=["GET", "POST"])
def ambientes():
    if request.method == "POST":
        try:
            capacidad = db.normalizar_entero(
                request.form.get("capacidad"), minimo=0, maximo=1000, default=45)
        except ValueError as exc:
            flash(str(exc), "danger")
            capacidad = None
        accion = request.form.get("accion")
        if accion == "crear" and capacidad is not None:
            codigo = (request.form.get("codigo") or "").strip().upper()
            if not codigo:
                flash("El código del ambiente es obligatorio.", "danger")
            else:
                existe = db.query("SELECT id FROM salones WHERE codigo=?", (codigo,))
                if existe:
                    flash("Ese ambiente ya existe.", "warning")
                else:
                    db.execute("INSERT INTO salones (codigo,capacidad,edificio,es_camillas) VALUES (?,?,?,?)",
                               (codigo, capacidad,
                                request.form.get("edificio", "Núcleo Palo Verde"),
                                1 if request.form.get("es_camillas") else 0))
                    flash("Ambiente creado.", "success")
        elif accion == "eliminar":
            try:
                db.execute("DELETE FROM salones WHERE id=?", (int(request.form["id"]),))
                flash("Ambiente eliminado.", "success")
            except Exception:
                flash("No se puede eliminar: tiene clases asignadas.", "danger")
        elif accion == "editar" and capacidad is not None:
            try:
                db.execute("UPDATE salones SET capacidad=?, edificio=?, es_camillas=? WHERE id=?",
                           (capacidad, request.form.get("edificio", ""),
                            1 if request.form.get("es_camillas") else 0, int(request.form["id"])))
                flash("Ambiente actualizado.", "success")
            except Exception as exc:
                flash(f"Error: {exc}", "danger")
    filas = db.query("""SELECT s.*, (SELECT COUNT(*) FROM asignaciones_horario a WHERE a.salon_id=s.id) AS usos
                         FROM salones s""")
    grupos = db.agrupar_ambientes(db.ambientes_oficiales(filas))
    return render_template("ambientes.html", salones=db.ambientes_oficiales(filas),
                           grupos=grupos, sectores=db.SECTORES_AMBIENTE)


# ── Docentes + Bloqueos de día y hora ──────────────────────────────────
@app.route("/docentes", methods=["GET", "POST"])
def docentes():
    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            pid = int(request.form["id"])
            if accion == "editar":
                cedula = db.normalizar_cedula(request.form.get("cedula", ""))
                db.execute("UPDATE profesores SET nombre=?, cedula=?, email=?, condicion=?, mencion=? WHERE id=?",
                           ((request.form.get("nombre") or "").strip().upper(),
                            cedula, request.form.get("email", ""),
                            request.form.get("condicion", "Contratado/a"),
                            request.form.get("mencion", ""), pid))
                flash("Docente actualizado.", "success")
            elif accion == "eliminar":
                db.execute("DELETE FROM profesores WHERE id=?", (pid,))
                flash("Docente eliminado.", "success")
        except Exception as exc:
            flash(f"Error: {exc}", "danger")
    profesores = queries.profesores()
    condiciones = sorted(
        set(constantes.CONDICIONES_DOCENTE)
        | {(p["condicion"] or "").strip() for p in profesores if (p["condicion"] or "").strip()},
        key=lambda s: (s.casefold(), s))
    sectores_disponibles = [s for s, _ in db.SECTORES_AMBIENTE]
    return render_template(
        "docentes.html",
        profesores=profesores,
        condiciones=condiciones,
        bloqueos=queries.obtener_bloqueos(solo_activos=False),
        sectores=sectores_disponibles,
        ambientes=queries.salones(),
        franjas=queries.obtener_franjas_sistema(),
        dias=db.DIAS_ORDEN,
    )


@app.route("/bloqueos/guardar", methods=["POST"])
def guardar_bloqueo_route():
    """Crea o edita un bloqueo de día y hora (piso, ambiente, docente o general)."""
    try:
        tipo = (request.form.get("tipo") or "piso").strip().lower()
        if tipo == "piso":
            objetivo = (request.form.get("objetivo_piso") or request.form.get("objetivo") or "").strip()
        elif tipo == "ambiente":
            objetivo = (request.form.get("objetivo_ambiente") or request.form.get("objetivo") or "").strip()
        elif tipo == "docente":
            objetivo = (request.form.get("objetivo_docente") or request.form.get("objetivo") or "").strip()
        else:
            objetivo = "Todos los ambientes"

        todo_el_dia = bool(request.form.get("todo_el_dia"))
        activo = bool(request.form.get("activo", "1")) if "bloqueo_id" in request.form and request.form.get("bloqueo_id") else True
        if request.form.get("es_edicion") == "1":
            activo = bool(request.form.get("activo"))

        blq = queries.guardar_bloqueo(
            bloqueo_id=(request.form.get("bloqueo_id") or "").strip() or None,
            tipo=tipo,
            objetivo=objetivo,
            dia=(request.form.get("dia") or "").strip(),
            todo_el_dia=todo_el_dia,
            hora_inicio=(request.form.get("hora_inicio") or "").strip(),
            hora_fin=(request.form.get("hora_fin") or "").strip(),
            motivo=(request.form.get("motivo") or "").strip(),
            activo=activo,
        )
        msg = f"Bloqueo guardado: {queries.descripcion_bloqueo(blq)}."
        if request.form.get("reasignar_auto") and blq["activo"]:
            res = scheduler.generar_horarios_automaticos()
            msg += f" Horarios actualizados ({res['asignados']} asignados, {res['pendientes']} pendientes)."
        flash(msg, "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"No se pudo guardar el bloqueo: {exc}", "danger")
    return redirect(url_for("docentes", _anchor="bloqueos"))


@app.route("/bloqueos/<bid>/alternar", methods=["POST"])
def alternar_bloqueo_route(bid: str):
    """Activa o desactiva manualmente un bloqueo existente."""
    blq = queries.alternar_bloqueo(bid)
    if not blq:
        flash("El bloqueo seleccionado no existe.", "warning")
    else:
        estado_txt = "activado" if blq["activo"] else "desactivado"
        res = scheduler.generar_horarios_automaticos()
        flash(
            f"Bloqueo {estado_txt}: {queries.descripcion_bloqueo(blq)}. "
            f"Horarios actualizados ({res['asignados']} asignados, {res['pendientes']} pendientes).",
            "success" if blq["activo"] else "info",
        )
    return redirect(url_for("docentes", _anchor="bloqueos"))


@app.route("/bloqueos/<bid>/eliminar", methods=["POST"])
def eliminar_bloqueo_route(bid: str):
    if queries.eliminar_bloqueo(bid):
        res = scheduler.generar_horarios_automaticos()
        flash(
            f"Bloqueo eliminado. Horarios actualizados ({res['asignados']} asignados, "
            f"{res['pendientes']} pendientes).",
            "success",
        )
    else:
        flash("El bloqueo seleccionado no existe.", "warning")
    return redirect(url_for("docentes", _anchor="bloqueos"))


@app.route("/docente/<int:pid>")
def docente_detalle(pid: int):
    prof = db.query("SELECT * FROM profesores WHERE id=?", (pid,))
    if not prof:
        flash("Docente no encontrado.", "warning")
        return redirect(url_for("docentes"))
    return render_template("calendario_profesores.html", profesor=prof[0],
                           asignaciones=queries.asignaciones_profesor(pid),
                           dias=db.DIAS_ORDEN)


# ── Carreras ───────────────────────────────────────────────────────────
@app.route("/carreras")
def carreras():
    return render_template(
        "carreras.html",
        carreras=queries.carreras_con_pensum(),
        duplicadas=queries.detectar_carreras_duplicadas(),
        sin_pensum=queries.carreras_sin_pensum(),
    )


@app.route("/carreras/sanear", methods=["POST"])
@app.route("/carreras/reparar-todo", methods=["POST"])
def sanear_carreras():
    try:
        r = _reparar_bd_completa(forzar_plan=True)
        partes = []
        if r["carreras_fusionadas"]:
            partes.append(f"{r['carreras_fusionadas']} carrera(s) duplicada(s) fusionada(s)")
        if r["carreras_vacias_eliminadas"]:
            partes.append(f"{r['carreras_vacias_eliminadas']} carrera(s) vacía(s) eliminada(s)")
        if r["materias_fusionadas"]:
            partes.append(f"{r['materias_fusionadas']} materia(s) repetida(s) unificada(s)")
        if r["pensum_plan_restaurado"]:
            partes.append(f"{r['pensum_plan_restaurado']} materias y horas restauradas del Plan de Estudio 2024")
        if r["pensum_backup_restaurado"]:
            partes.append(f"{r['pensum_backup_restaurado']} materias recuperadas desde respaldo local")
        if r["pensum_pnf_restaurado"]:
            partes.append(f"{r['pensum_pnf_restaurado']} materias PNF restauradas")
        if partes:
            flash("Reparación completada: " + "; ".join(partes) + ".", "success")
        else:
            flash("La base de datos está limpia y con su pensum completo.", "info")
    except Exception as exc:
        flash(f"Error durante la reparación (se conservó el respaldo): {exc}", "danger")
    return redirect(url_for("carreras"))


@app.route("/respaldar-bd", methods=["POST"])
def respaldar_bd_route():
    try:
        ruta = db.respaldar_bd("manual")
        if ruta:
            flash(f"Respaldo creado correctamente en data/backups/{ruta.name}", "success")
        else:
            flash("Los respaldos locales solo aplican cuando se usa base SQLite.", "info")
    except Exception as exc:
        flash(f"Error al crear respaldo: {exc}", "danger")
    return redirect(request.referrer or url_for("carreras"))


@app.route("/api/carreras/<int:carrera_id>/horario")
def api_horario_carrera(carrera_id: int):
    if not db.query("SELECT id FROM carreras WHERE id=?", (carrera_id,)):
        return jsonify({"error": "Carrera no encontrada"}), 404
    return jsonify({dia: filas for dia, filas in queries.horario_por_carrera(carrera_id).items()})


@app.route("/api/franjas-horario", methods=["GET", "POST"])
def api_franjas_horario():
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "franjas": queries.obtener_franjas_sistema(),
            "franjas_defecto": [list(f) for f in queries.FRANJAS_POR_DEFECTO],
        })
    payload = request.get_json(silent=True) or {}
    franjas = payload.get("franjas")
    try:
        guardadas = queries.guardar_franjas_sistema(franjas)
        return jsonify({"ok": True, "franjas": guardadas})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No se pudo guardar el horario: {exc}"}), 500


@app.route("/api/franjas-horario/restaurar", methods=["POST"])
def api_restaurar_franjas():
    try:
        franjas = queries.restaurar_franjas_por_defecto()
        return jsonify({"ok": True, "franjas": franjas})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Reportes ───────────────────────────────────────────────────────────
@app.route("/reporte")
def reporte():
    carrera_id = request.args.get("carrera_id", type=int)
    if carrera_id:
        if not db.query("SELECT id FROM carreras WHERE id=?", (carrera_id,)):
            flash("Carrera inválida; se generó el reporte completo.", "warning")
            carrera_id = None
    html = reports.reporte_por_carrera(carrera_id, incluir_profesores=request.args.get("profesores") == "1")
    if request.args.get("descargar") == "1":
        return Response(html, mimetype="text/html", headers={
            "Content-Disposition": "attachment; filename=Horario_Por_Carrera.html"})
    return html


@app.route("/reporte-imprimible")
def reporte_imprimible():
    return redirect(url_for("reporte", **request.args.to_dict()))


@app.route("/vaciar", methods=["POST"])
def vaciar():
    db.limpiar_carga_academica()
    flash("Clases, carga académica y disponibilidades eliminadas. Se conservaron "
          "carreras, docentes, materias, pensum y ambientes.", "success")
    return redirect(url_for("index"))


@app.route("/api/estadisticas")
def api_stats():
    return jsonify(db.estadisticas())


def _hora_valida(valor: str) -> bool:
    try:
        h, m = valor.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except Exception:
        return False


def _entero(valor, default=0) -> int:
    try:
        return db.normalizar_entero(valor, default=default)
    except ValueError:
        return int(default)
