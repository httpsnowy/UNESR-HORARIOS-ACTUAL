"""Genera el ejecutable multiplataforma con PyInstaller.

Uso:
    python scripts/build_exe.py            # detecta el sistema actual
    python scripts/build_exe.py --onefile  # un solo archivo (más lento al iniciar)

Salida: dist/UNESR_Horarios[.exe]
Incluye: plantillas, logo, base SQLite inicial, uploads y plan de estudio.

Windows: compilar DENTRO de Windows (un .exe no se puede generar en Linux).
Requiere: pip install -r requirements.txt
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "UNESR_Horarios"


def build(onefile: bool = False) -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("Falta PyInstaller: pip install pyinstaller")

    sep = ";" if sys.platform == "win32" else ":"
    datos = [
        (str(ROOT / "app" / "templates"), "app/templates"),
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "data"), "data"),
        (str(ROOT / "uploads"), "uploads"),
        (str(ROOT / ".env.example"), "."),
    ]
    comando = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        "--paths", str(ROOT),
        "--hidden-import", "webview",
        "--hidden-import", "httpx",
        "--hidden-import", "openpyxl",
        "--collect-data", "webview",
    ]
    # Solo se empaquetan los backends de ventana realmente instalados. Así el
    # mismo exe funciona en escritorios con GTK o con Qt (CachyOS/Cosmic, KDE…).
    for modulo in ("webview.platforms.gtk", "webview.platforms.qt",
                   "webview.platforms.winforms", "qtpy", "PySide6", "PyQt6", "gi"):
        try:
            if importlib.util.find_spec(modulo):
                comando += ["--hidden-import", modulo]
        except (ImportError, ValueError):
            pass
    if onefile:
        comando.append("--onefile")
    else:
        comando.append("--onedir")
    # En Windows, sin consola; en Linux se deja para diagnóstico.
    if sys.platform == "win32":
        comando.append("--noconsole")
    for origen, destino in datos:
        if Path(origen).exists():
            comando += ["--add-data", f"{origen}{sep}{destino}"]

    # pdftotext se usa para importar el pensum de los 3 PNF desde PDF.
    binario_pdf = "pdftotext.exe" if sys.platform == "win32" else "pdftotext"
    ruta_pdf = shutil.which(binario_pdf)
    if ruta_pdf:
        comando += ["--add-binary", f"{ruta_pdf}{sep}bin"]

    # Icono opcional
    ico = ROOT / "assets" / "UNESR.ico"
    if ico.exists():
        comando += ["--icon", str(ico)]

    comando.append(str(ROOT / "main.py"))
    print("Ejecutando:", " ".join(comando))
    subprocess.run(comando, cwd=ROOT, check=True)

    destino_final = ROOT / "dist" / (NAME + (".exe" if sys.platform == "win32" else ""))
    print(f"\n✓ Ejecutable generado: {destino_final}")
    print("Copia también la carpeta .env si usas Supabase (o crea uno nuevo desde .env.example).")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--onefile", action="store_true")
    a = p.parse_args()
    build(a.onefile)
