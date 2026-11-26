"""Punto de entrada del Sistema UNESR de Oferta Académica y Horarios.

Arquitectura: Flask (servidor local) + pywebview (ventana nativa).
Sin Flet, sin Flask externo, sin DLLs nativas: funciona igual en Windows y Linux
y se empaqueta con PyInstaller sin problemas.

Uso:
    python main.py              -> ventana de escritorio (pywebview)
    python main.py --browser    -> abre el navegador del sistema
    python main.py --server     -> solo servidor (para red local)
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.web import app  # noqa: E402


def puerto_libre(preferido: int = 8765) -> int:
    for p in range(preferido, preferido + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return preferido


def esperar_servidor(url: str, timeout: float = 60.0) -> bool:
    import httpx
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            # Con Supabase la primera petición puede tardar varios segundos:
            # un timeout de 1 s cerraba el programa antes de que arrancara.
            if httpx.get(url, timeout=10.0).status_code == 200:
                return True
        except Exception:
            time.sleep(0.15)
    return False


def elegir_gui() -> str | None:
    """Devuelve el backend que se le pasará a ``webview.start``.

    * ``UNESR_GUI=browser`` salta directamente al navegador.
    * ``UNESR_GUI=qt|gtk|edgechromium`` fuerza uno concreto (diagnóstico).
    * Windows usa WinForms + WebView2 (``edgechromium``), nunca Qt.
    * Linux deja que pywebview pruebe GTK → Qt, salvo que sepamos de antemano
      que GTK no está disponible y Qt sí: así evitamos el traceback de ``gi``.
    """
    import importlib.util

    forzado = os.environ.get("UNESR_GUI", "").strip().lower()
    if forzado:
        return forzado if forzado != "browser" else "browser"
    if sys.platform == "win32":
        return "edgechromium"
    if sys.platform.startswith("linux") and importlib.util.find_spec("qtpy") \
            and not importlib.util.find_spec("gi"):
        return "qt"
    return None


def registrar_error_gui(exc: BaseException) -> None:
    """Guarda el traceback para poder diagnosticar el exe sin consola."""
    import traceback

    texto = (f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
             f"No se pudo abrir la ventana nativa\n"
             + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    print(texto, file=sys.stderr)
    try:
        ruta = db.base_escritura / "webview_error.log"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
        print(f"Diagnóstico guardado en {ruta}", file=sys.stderr)
    except Exception:
        pass
    if getattr(sys, "frozen", False) and not sys.platform.startswith("win32"):
        print(
            "Estás usando el binario compilado en otra máquina: dentro de él no "
            "están los módulos 'gi' (GTK) ni 'qtpy' (Qt). Ejecuta "
            "'./iniciar_sistema.sh' para usar el código fuente, o recompila "
            "aquí con 'pip install -r requirements.txt'.",
            file=sys.stderr,
        )


def abrir_en_navegador(url: str) -> None:
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return


def main() -> None:
    db.init_db()
    puerto = int(os.environ.get("UNESR_PORT", puerto_libre()))
    url = f"http://127.0.0.1:{puerto}/"
    modo = sys.argv[1] if len(sys.argv) > 1 else "--desktop"

    # En modo servidor no hay ventana que esperar: se ejecuta en el hilo
    # principal para que Ctrl+C funcione y no dependa de sondeos con timeout.
    if modo == "--server":
        print(f"UNESR Horarios ejecutándose en {url}")
        print("Modo servidor. Presione Ctrl+C para detener.")
        try:
            app.run(host="127.0.0.1", port=puerto, debug=False,
                    use_reloader=False, threaded=True)
        except KeyboardInterrupt:
            pass
        return

    servidor = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=puerto, debug=False,
                               use_reloader=False, threaded=True),
        daemon=True,
    )
    servidor.start()
    if not esperar_servidor(url):
        print("No se pudo iniciar el servidor local.", file=sys.stderr)
        return

    print(f"UNESR Horarios ejecutándose en {url}")

    gui = elegir_gui()
    if modo == "--browser" or os.environ.get("UNESR_FORCE_BROWSER") or gui == "browser":
        abrir_en_navegador(url)
        return

    # Escritorio nativo con pywebview. Si falla, dejamos el traceback en un
    # archivo de diagnóstico y abrimos el navegador para no perder el acceso.
    try:
        import webview

        webview.create_window(
            title="UNESR — Oferta Académica y Horarios · Núcleo Palo Verde",
            url=url,
            width=1360,
            height=860,
            min_size=(980, 620),
            resizable=True,
            background_color="#F8FAFC",
        )
        webview.start(**({"gui": gui} if gui else {}))
    except Exception as exc:  # pragma: no cover
        registrar_error_gui(exc)
        print(f"Abriendo en el navegador: {url}", file=sys.stderr)
        abrir_en_navegador(url)


if __name__ == "__main__":
    main()
