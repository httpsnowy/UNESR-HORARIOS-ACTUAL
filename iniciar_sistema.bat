@echo off
CHCP 65001 >nul
TITLE UNESR - Oferta Academica y Horarios
cd /d "%~dp0"

REM Igual que iniciar_sistema.sh: por defecto usa el codigo fuente para que
REM pywebview encuentre pythonnet y abra la ventana WinForms/WebView2.
REM Para forzar el exe: iniciar_sistema.bat --binario
set USAR_BINARIO=0
:parsear
if "%~1"=="" goto listo
if /I "%~1"=="--binario" set USAR_BINARIO=1
shift
goto parsear
:listo

set "BINARIO=%~dp0dist\UNESR_Horarios\UNESR_Horarios.exe"
if "%USAR_BINARIO%"=="1" (
  if exist "%BINARIO%" (
    start "" "%BINARIO%"
    exit /b 0
  )
  echo [AVISO] No existe %BINARIO%; se usara el codigo fuente.
)

if not exist ".venv" (
  echo Creando entorno virtual...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt --quiet
python main.py %*
pause
