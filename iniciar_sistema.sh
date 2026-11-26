#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Por defecto se usa el CÓDIGO FUENTE, no el binario de dist/.
# Motivo: un ejecutable PyInstaller compilado en otra máquina no ve los módulos
# gráficos del sistema ('gi' para GTK o 'qtpy' para Qt) y pywebview termina
# abriendo el navegador. Con el código fuente, pywebview sí los encuentra.
# Si quieres fuerza el binario: ./iniciar_sistema.sh --binario
usar_binario=0
args=()
for arg in "$@"; do
  case "$arg" in
    --binario) usar_binario=1 ;;
    *) args+=("$arg") ;;
  esac
done

BINARIO="./dist/UNESR_Horarios/UNESR_Horarios"

ejecutar_codigo() {
  if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv .venv
  fi
  source .venv/bin/activate
  python -m pip install -r requirements.txt --quiet
  python main.py "${args[@]}"
}

if [ "$usar_binario" -eq 1 ]; then
  if [ -x "$BINARIO" ]; then
    exec "$BINARIO" "${args[@]}"
  fi
  echo "[AVISO] No existe $BINARIO; se usará el código fuente." >&2
fi

if [ -x ".venv/bin/python" ]; then
  ejecutar_codigo
elif [ -x "$BINARIO" ]; then
  exec "$BINARIO" "${args[@]}"
else
  ejecutar_codigo
fi
