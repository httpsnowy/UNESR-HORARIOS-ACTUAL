@echo off
REM ============================================================
REM  UNESR Horarios - generar UNESR_Horarios.exe en WINDOWS
REM  Ejecutar desde una terminal (PowerShell o CMD) dentro de Windows.
REM  PyInstaller NO puede compilar un .exe de Windows desde Linux.
REM ============================================================
setlocal
cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python no esta en el PATH. Instala Python 3.11 o 3.12 de 64 bits.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creando entorno virtual...
  python -m venv .venv
)

echo [2/4] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m pip install pyinstaller

echo [3/4] Verificando pdftotext (poppler-for-windows)...
where pdftotext.exe >nul 2>nul
if errorlevel 1 (
  echo [AVISO] pdftotext.exe no esta en el PATH.
  echo         Descarga poppler-for-windows y agrega su carpeta bin al PATH.
  echo         Sin el, la recarga de los PNF desde PDF no funcionara.
)

echo [4/4] Compilando...
".venv\Scripts\python.exe" scripts\build_exe.py

echo.
echo Listo: dist\UNESR_Horarios\UNESR_Horarios.exe
echo Copia tu archivo .env junto al .exe (o a %%APPDATA%%\UNESR_Horarios\.env).
pause
