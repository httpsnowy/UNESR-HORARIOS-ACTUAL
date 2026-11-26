# UNESR — Sistema de Oferta Académica y Horarios

Núcleo Palo Verde · Periodo 2026-2

Reescritura limpia del sistema original (Flet + Flask + SQLite) en una sola
aplicación **Flask + pywebview**, empaquetable con **PyInstaller** en Windows y
Linux, con **Supabase** como backend opcional y SQLite como respaldo local.

---

## 1. Qué se corrigió respecto al sistema original

| Requisito | Antes | Ahora |
|---|---|---|
| Asignación de ambientes | El generador borraba **todas** las asignaciones (incluidas las manuales) y podía duplicar docente en hora fija | Respeta disponibilidad del docente, evita choques de docente/ambiente, conserva reasignaciones `Manual` y regenera el resto |
| Materias por carrera | Catálogo hardcodeado de 7–9 materias y recorte a `pensum[:12]` | Pensum completo: **9 carreras** del Excel **PLAN DE ESTUDIO 2024** (653 filas, 632 únicas) **+ 3 PNF desde PDF** (156 unidades) = 788 unidades curriculares en 12 carreras |
| Horario por carrera | Oferta general de todas las carreras juntas | **Cuadro día × hora por una sola carrera** (sin opción "todas"), con vista lista opcional |
| Filtro por carrera | Mezclaba nombres y no validaba IDs | Select validado; IDs inexistentes se descartan con aviso; API devuelve 404 |
| Interfaz | Flet (dependencia frágil en Windows) + Flask, Bootstrap por CDN | Una sola UI web autocontenida (sin CDN, funciona offline) dentro de ventana nativa; carga múltiple validada, cuadro de horarios y búsqueda dinámica de docentes |
| Empaquetado | Flet usa APIs privadas y un cliente nativo externo; `.exe` fallaba | Sin Flet ni DLLs nativas; pywebview + httpx (PostgREST) → PyInstaller confiable |
| Base de datos | SQLite local / PostgreSQL con DLLs | Supabase vía HTTPS (sin `psycopg`/DLLs) con fallback automático a SQLite |

**Resultado verificado:** el generador asigna ambientes sin crear choques y
reporta explícitamente los bloques que no puede ubicar. La base semilla conserva
**440 asignaciones históricas con horas fijas y 6 colisiones** (3 de ambiente,
1 de docente y 2 de docente + ambiente, las cuales bajaron de 17 al normalizar
el inventario de ambientes): el Dashboard las muestra con su motivo y la carrera
afectada permite reasignarlas a mano. Esas reasignaciones quedan marcadas como
`Manual` y se conservan si luego se regenera el horario.

### Mejoras de frontend

- **Nueva Carga → Carga múltiple manual:** botón *＋ Agregar materia* para
  registrar varias fichas en un solo envío (mismo docente con varias materias o
  varios docentes). `app/carga_multiple.py` valida **antes de escribir**:
  docente duplicado en el mismo día/hora, ambiente preferido duplicado y
  choques con reasignaciones `Manual`. Si hay error, no se guarda nada y se
  muestran las filas corregidas. Después se regenera la asignación automática.
- **Nueva Carga → materias por carrera:** al elegir la carrera (en la ficha
  individual y en cada fila de la carga múltiple), el `datalist` de materias
  muestra **solo las unidades curriculares cargadas para esa carrera**
  (pensum + catálogo). Si se cambia de carrera, se descarta la materia que ya
  no pertenece; si la carrera es nueva, se muestran todas como fallback.
- **Condición del docente:** nueva campo en la ficha individual y en cada fila
  de la carga múltiple, con sugerencias del documento oficial de oferta
  (`Contratado Nuevo`, `Contratado Anterior`, `Ordinario`, categorías
  `Instructor`/`Asistente`/`Agregado`/`Asociado`/`Titular` y dedicaciones
  `Exclusiva`/`Tiempo Completo`/`Medio Tiempo`/`Tiempo Convencional`). Se puede
  escribir cualquier otro valor. Se guarda en `profesores` y alimenta el filtro
  de Docentes.
- **Horarios:** el selector ya no ofrece "Todas las carreras". Al elegir una
  carrera se muestra un **cuadro real Lunes–Sábado × franjas horarias**; cada
  celda contiene materia, docente, ambiente y sección. Botón *Lista* para ver el
  detalle agrupado por día de esa misma carrera. Los PNF muestran un aviso
  explícito cuando **el pensum está cargado pero no hay docentes asignados**
  (los PDF traen la malla, no fichas docentes), con el listado de materias
  pendientes y enlace a *Nueva Carga*.
- **Vaciar datos:** ahora **solo elimina asignaciones, carga académica y
  disponibilidades**. Conserva carreras, docentes, materias, pensum, facultades
  y ambientes, para poder regenerar el horario sin perder los catálogos.
- **Colisiones visibles:** en **Horarios**, las clases involucradas en una
  colisión aparecen **en rojo** en el cuadro y en la vista *Lista*, con el motivo
  (`docente`, `ambiente` o `docente y ambiente`). En el **Dashboard** hay un
  desplegable «Colisiones actuales» con cada par de clases, el día y rato de
  solape, las dos fichas enfrentadas, la causa y si conviene regenerar
  automáticamente o reasignar a mano. En la carrera afectada, otro desplegable
  permite **reasignar la clase A o la B** (ambiente, día y hora) sin tocar las
  demás; esa reasignación queda marcada como `Manual` y sobrevive a la
  regeneración.
- **Ambientes:** se corrigió el «cuadrado/semicírculo roto»: los checkboxes ya
  no heredan el borde redondeado de los inputs de texto, las píldoras no se
  parten en dos líneas, la tabla usa `table-layout: fixed` con `colgroup` y los
  formularios de acciones son `inline-flex`. La capacidad se edita sin borrar el
  edificio ni el tipo de ambiente.
- **Campos depurados:** créditos, bloques y capacidad solo aceptan **enteros**
  (se rechazan `3.5`, `1e3`, texto y negativos) con rangos 0–30, 1–7 y 0–1000;
  las cédulas se normalizan a `V-1234567` / `E-12345678`, aceptando puntos de
  miles (`V-1.234.567`). La validación está en el servidor y en el navegador.
- **Supabase sin errores 42703:** el traductor de `db._rest_query()` ya no envía
  `AS`, `DISTINCT` ni fragmentos de SQL como parámetro `select` de PostgREST; los
  alias se reaplican en Python, `DISTINCT` se deduplica en Python y los JOINs /
  subconsultas van a la caché SQLite remota. Tampoco se ignoran condiciones
  `WHERE` no traducidas (antes filtraban de forma silenciosa).
- **Docentes:** buscador instantáneo por nombre/cédula/mención (sin acentos) y
  filtro por condición, con contador de resultados y botón *Limpiar*.
- Accesibilidad/rendimiento: etiquetas y `aria-*` en los nuevos controles,
  navegación por teclado, `:focus-visible`, `prefers-reduced-motion`, filtrado
  en cliente (sin recargas) y CSS autocontenido en `base.html`.

---

## 2. Estructura

```
UNESR_TEST_BRANCH/
├── app/
│   ├── db.py            # Capa unificada Supabase (PostgREST) / SQLite
│   ├── importers.py     # Plan de estudio + oferta 2026-2
│   ├── pdf_importers.py # Pensum de los 3 PNF desde los PDF oficiales
│   ├── carga_multiple.py# Carga manual de varias materias + validación
│   ├── constantes.py    # Condiciones docentes del documento oficial
│   ├── scheduler.py     # Asignación automática corregida
│   ├── queries.py       # Carreras, pensum, horario por carrera/día, filtros
│   ├── reports.py       # Reporte por carrera y día (sin oferta general)
│   ├── web.py           # Rutas Flask
│   └── templates/       # UI autocontinida
├── sql/schema.sql       # Esquema PostgreSQL/Supabase
├── scripts/
│   ├── migrate_to_supabase.py
│   ├── normalizar_ambientes.py  # deja solo los 41 salones oficiales
│   └── build_exe.py
├── data/                # BD semilla, plan de estudio y oferta
├── assets/UNESR.png
├── tests/               # 41 pruebas automatizadas
├── main.py              # Entry point (Flask + pywebview)
├── .env.example
└── requirements.txt
```

---

## 3. Instalación y arranque

### Windows (PowerShell)

```powershell
cd UNESR_Horarios
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

O doble clic en `iniciar_sistema.bat` (crea el venv e instala dependencias
automáticamente).

### Linux / macOS

```bash
cd UNESR_Horarios
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x iniciar_sistema.sh
./iniciar_sistema.sh
```

> `cd UNESR_Horarios` asume que clonaste el repo (o descomprimiste el ZIP) con
> ese nombre. Si tu carpeta se llama distinto, cambia ese `cd` por tu ruta real.

### Modos alternativos

```bash
# Usa SIEMPRE el intérprete del entorno virtual (ahí están las dependencias).
.venv/bin/python main.py --browser   # abre el navegador del sistema
.venv/bin/python main.py --server    # solo servidor local (127.0.0.1:8765)
# Windows: .venv\Scripts\python.exe main.py --server
```

> Si ejecutas `python main.py` con el Python del sistema aparecerá
> `ModuleNotFoundError: No module named 'flask'`. En ese caso, instala antes
> las dependencias con `.venv/bin/python -m pip install -r requirements.txt`
> o usa siempre `.venv/bin/python`. Alternativamente, ejecuta el `.exe` ya
> compilado en `dist/UNESR_Horarios/`.

Si no hay credenciales de Supabase, el sistema usa automáticamente
`data/universidad_horarios.db` (SQLite) con todos los datos originales.

---

## 4. Base de datos

### 4.1 Modo local (por defecto)

No hay que hacer nada: la BD semilla ya incluye **12 carreras** con sus
**788 unidades curriculares**, 111 docentes, 41 ambientes oficiales y 440 asignaciones
(clases que estaban en ambientes externos se reubicaron a salones oficiales
respetando sus capacidades y evitando solapes; ver sección 8)
históricas. Los 3 PNF se importan de estos PDFs en `uploads/`:

| PNF | PDF | Unidades |
|---|---|---|
| PNF Fisioterapia | `DOCUMENTO_RECTOR_FISIOTERAPIA_(1).pdf` | 57 |
| PNF Veterinaria | `Malla_Curricular_-_PNF_en_Medicina_Veterinaria.pdf` | 55 |
| PNF Agroecología | `Récord_Académico_-_Mercedes_Mireya_Rodríguez_Muñoz.pdf` | 44 |

Para recargarlos en cualquier momento: **Herramientas → Cargar PNF (PDF)**
(o `POST /cargar-pnfs`). Igualmente, **Herramientas → Cargar plan de estudio**
vuelve a importar el Excel de 2024 (`POST /cargar-plan-estudio`). Ambas cargas
son idempotentes. Requiere el comando `pdftotext` (poppler):

```bash
# Linux (Debian/Ubuntu)
sudo apt-get install poppler-utils
# Windows: descargar poppler-for-windows y agregar la carpeta bin al PATH
```

### 4.2 Migrar a Supabase

**Paso 1 — crear el proyecto en Supabase** y obtener:
- `Project URL` (Settings → API)
- `service_role secret key` (Settings → API → service_role)

**Paso 2 — configurar `.env`:**

```bash
cp .env.example .env
```

Editar `.env` (con `auto` funciona tanto para migrar como para usar la app;
si hay URL+KEY se conecta a Supabase y si no, usa SQLite):

```ini
DB_BACKEND=auto
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_KEY=TU_SERVICE_ROLE_KEY
DATABASE_PATH=data/universidad_horarios.db
```

> La URL está en **Project Settings → API → Project URL** y la key en
> **Project API keys → service_role (secret)**. No uses la `anon/public`.

**Paso 3 — crear las tablas** en Supabase → SQL Editor → New query, pegar todo
`sql/schema.sql` y Run.

**Paso 4 — migrar datos** (remapea todas las claves foráneas):

```bash
.venv/bin/python scripts/migrate_to_supabase.py --limpiar --plan
```

En Windows: `.venv\Scripts\python.exe scripts\migrate_to_supabase.py --limpiar --plan`

Opciones:
- `--limpiar`: vacía primero las tablas destino (recomendado en la primera migrate).
- `--plan`: importa las 653 filas del PLAN DE ESTUDIO 2024 **y** los 3 PNF desde PDF.
- `--pnf`: importa solo los 3 PNF (útil si ya migraste el plan 2024).

**Paso 5 — probar el funcionamiento**

Con `DB_BACKEND=auto` (o `supabase`) ya está activo; no hay que cambiar nada:

```bash
.venv/bin/python main.py --server
# en otra terminal:
curl http://127.0.0.1:8765/api/estadisticas
```

Debes ver `carreras: 12`, `planes_estudio: 788`, `materias: 789` y la barra
lateral debe mostrar **Base: supabase**.

Otras comprobaciones: `/horarios` (por carrera y día), `/carreras` (los 3 PNF
con 44/57/55 materias), `/reporte?descargar=1`, y los filtros de carrera/día.

```bash
.venv/bin/python -m unittest discover -s tests -v   # 41 pruebas, siempre locales
```

> No se necesitan archivos `.dll` ni `psycopg`: la conexión es HTTPS via
> PostgREST (`httpx`), compatible con PyInstaller en Windows.
>
> En el `.exe`, el `.env` **no se incrusta**: cópialo junto a `UNESR_Horarios.exe`
> o, en Windows, a `%APPDATA%\UNESR_Horarios\.env`. Así tus credenciales nunca
> quedan dentro del ejecutable ni en el repositorio.

### 4.3 Si usas la `anon key` en lugar de `service_role`

Activa RLS en Supabase y crea una política por tabla, por ejemplo:

```sql
ALTER TABLE carreras ENABLE ROW LEVEL SECURITY;
CREATE POLICY "acceso_app" ON carreras FOR ALL USING (true) WITH CHECK (true);
-- Repetir para facultades, salones, profesores, disponibilidades,
-- planes_estudio, materias, carga_academica, asignaciones_horario, configuracion.
```

---

## 5. Generar el ejecutable (guía para el equipo)

**Regla de oro:** el ejecutable se compila **en el mismo sistema donde se va a
usar**. PyInstaller no puede crear un `.exe` de Windows desde Linux, ni un binario
de Linux desde Windows. Si tienes Windows, sigue la sección A; si tienes Linux,
la sección B.

| Tu sistema | Sección | Archivo que obtienes |
|---|---|---|
| Windows 10/11 de 64 bits | A | `dist\UNESR_Horarios\UNESR_Horarios.exe` |
| Linux de 64 bits | B | `dist/UNESR_Horarios/UNESR_Horarios` |

### Antes de empezar (haz esto en TU PC, una sola vez)

1. **Descarga el código** (o pide la carpeta del proyecto):
   ```powershell
   git clone https://github.com/0800NightDev/UNESR_Horarios.git
   cd UNESR_Horarios
   ```
   Si no tienes Git, entra a la URL, pulsa **Code → Download ZIP**, descomprime
   y abre una terminal dentro de la carpeta resultante.

2. **Instala Python 3.11 o 3.12 de 64 bits** desde <https://www.python.org/downloads/>.
   - En Windows, durante la instalación marca ✅ **“Add python.exe to PATH”**.
   - Comprueba que funciona:
     ```powershell
     python --version
     ```
     Debe decir `Python 3.11.x` o `Python 3.12.x`. Si dice `Python 3.10` o sale
     “no se reconoce”, instala la versión correcta y vuelve a abrir la terminal.

3. **Crea tu archivo de conexión a la base de datos.** Copia la plantilla y
   rellena tus valores:
   ```powershell
   copy .env.example .env        # Windows
   cp .env.example .env          # Linux
   ```
   - Si vas a usar **Supabase**, pega tu `SUPABASE_URL` y `SUPABASE_KEY` reales
     en el `.env`. **Nunca subas ese `.env` a GitHub** (ya está en `.gitignore`).
   - Si quieres probar **sin internet / sin Supabase**, deja
     `DB_BACKEND=sqlite`: el sistema usa la base de datos semilla incluida y
     funciona igual, con los mismos datos de ejemplo.

4. **Ten conexión a internet la primera vez** (para descargar las librerías con
   `pip`). Después el ejecutable funciona sin internet si usas `sqlite`.

### A. Compilar en Windows (generar el `.exe`)

Abre **PowerShell** dentro de la carpeta del proyecto y ejecuta, en orden:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\scripts\build_windows.bat
```

El `.bat` hace exactamente lo mismo que estos comandos manuales (úsalos si el
`.bat` falla):

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe scripts\build_exe.py
```

**Resultado:** `dist\UNESR_Horarios\UNESR_Horarios.exe` junto a una carpeta
`_internal`. **Copia toda la carpeta `dist\UNESR_Horarios`**, no solo el `.exe`.

Para probarlo:

```powershell
cd dist\UNESR_Horarios
copy ..\..\.env .env        # si usas Supabase; si no, omitelo
.\UNESR_Horarios.exe        # ventana nativa
.\UNESR_Horarios.exe --server   # o modo navegador en http://127.0.0.1:5000
```

Notas importantes de Windows:

- Si prefieres **un solo archivo**:
  `.\.venv\Scripts\python.exe scripts\build_exe.py --onefile` (tarda más en abrir).
- Para importar los PNF desde PDF hace falta `pdftotext.exe`: instala
  [poppler-for-windows](https://github.com/oschwartz10612/poppler-windows),
  descomprímelo y agrega su carpeta `bin` al **PATH**. Sin él, el resto del
  sistema funciona; solo falla la carga de PNF desde PDF.
- Si Windows Defender bloquea el binario: **Seguridad de Windows → Protección
  contra virus → Exclusiones → Agregar carpeta** y elige `dist`.
- Si al abrir sale una pantalla negra, usa `--server` y abre el navegador; es
  una limitación del WebView en algunas máquinas, no un error de datos.
- Los datos se guardan en `%APPDATA%\UNESR_Horarios\data\universidad_horarios.db`.

### B. Compilar en Linux

Abre una terminal dentro de la carpeta del proyecto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt pyinstaller
.venv/bin/python scripts/build_exe.py
```

Si el comando `python3 -m venv` dice *“ensurepip is not available”*, instala el
paquete de Python de tu distro, por ejemplo:
`sudo apt install python3-venv python3-pip` (Debian/Ubuntu) o
`sudo dnf install python3-pip` (Fedora).

**Resultado:** `dist/UNESR_Horarios/UNESR_Horarios`. Para probarlo:

```bash
cp .env dist/UNESR_Horarios/.env     # solo si usas Supabase
./dist/UNESR_Horarios/UNESR_Horarios         # ventana nativa (requiere WebKit/GTK)
./dist/UNESR_Horarios/UNESR_Horarios --server   # o navega a http://127.0.0.1:5000
```

Si la ventana nativa no abre en Linux, instala `python3-gi gir1.2-webkit2-4.0`
(o `libwebkit2gtk-4.1-0`) y usa `--server` mientras tanto.
Los datos se guardan en `~/.local/share/UNESR_Horarios/data/`.

### Comprobación rápida después de compilar

Abre la aplicación y confirma que:

1. El **Dashboard** muestra 12 carreras, 111 docentes, 789 materias y el
   desplegable **“Colisiones actuales”**.
2. En **Ambientes** aparecen exactamente **41 salones**:
   `P1-01…P1-08 → P2-09…P2-22 → P3-23…P3-27 → P4-28…P4-37 →
   SATELITAL-01/02 → VIRTUAL-01/02`, con encabezados de sección y numeración
   global consecutiva.
3. En **Horarios**, al elegir una carrera con colisiones, las clases aparecen
   **en rojo** y el panel permite reasignar.
4. No aparecen errores `42703` en la terminal ni en la interfaz.

Si algo falla, ejecuta antes las pruebas para localizar el problema:

```bash
.venv/bin/python -m unittest discover -s tests -v       # Linux
.\.venv\Scripts\python.exe -m unittest discover -s tests -v   # Windows
```

El bundle incluye plantillas, logo, base semilla, plan de estudio, `uploads` y
`pdftotext`. pywebview usa WinForms/WebView2 en Windows, y GTK o Qt en Linux
(se instalan automáticamente con `requirements.txt`).

### Si la ventana no abre y solo sale el navegador (Linux, p. ej. CachyOS + Cosmic)

Síntoma: en la terminal aparece algo como:

```
[pywebview] GTK cannot be loaded → ModuleNotFoundError: No module named 'gi'
[pywebview] QT cannot be loaded  → ModuleNotFoundError: No module named 'qtpy'
No se pudo abrir la ventana nativa (...). Abriendo en el navegador…
```

**Causa:** `iniciar_sistema.sh` antes daba prioridad al ejecutable de `dist/`.
Ese binario se compiló en otra máquina y dentro de él **no existen** los módulos
`gi` (GTK) ni `qtpy` (Qt). Tener Qt instalado en el sistema no basta: el
ejecutable empaquetado no puede ver los paquetes de Python del sistema.

**Solución (ya aplicada en el repo):** `./iniciar_sistema.sh` ahora usa primero
el **código fuente** con `.venv`, donde sí se instalan `qtpy` y `PySide6`.
Basta con:

```bash
cd UNESR_Horarios
git pull origin main
./iniciar_sistema.sh
```

Si todavía prefieres el binario, recompílalo **en tu PC** (así incluye Qt):

```bash
.venv/bin/python -m pip install -r requirements.txt pyinstaller
.venv/bin/python scripts/build_exe.py
./iniciar_sistema.sh --binario
```

En Wayland puro (Cosmic, KDE Wayland), si Qt dice *“Could not load the Qt
platform plugin 'wayland'”*, instala el plugin del sistema:

```bash
sudo pacman -S qt6-wayland      # CachyOS / Arch
```

Para forzar un backend y diagnosticar:

```bash
UNESR_GUI=qt   ./iniciar_sistema.sh     # fuerza Qt
UNESR_GUI=gtk  ./iniciar_sistema.sh     # fuerza GTK (requiere python-gobject + webkit2gtk)
UNESR_GUI=browser ./iniciar_sistema.sh  # solo navegador
```

El traceback completo se guarda en
`~/.local/share/UNESR_Horarios/webview_error.log` (Windows:
`%APPDATA%\UNESR_Horarios\webview_error.log`). Cualquier otro error de ventana
también cae al navegador para que el sistema nunca quede inaccesible.

---

## 6. Pruebas

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Cubre: pensum sin recorte, horario por carrera/día, filtros válidos e
inválidos, asignación sin conflictos, preservación de reasignaciones manuales,
carga/eliminación de datos, reportes y rutas web, además del traductor
PostgREST (sin 42703), la normalización de enteros/cédulas y el detalle de
colisiones con motivos y sugerencia de reasignación.

---

## 7. Subir a GitHub

Repositorio: `https://github.com/0800NightDev/UNESR_Horarios`.

Estado: **código verificado y publicado** en la rama `main` (41 pruebas en verde,
sin errores `42703`). Para bajar la última versión en otro equipo:

```bash
git clone https://github.com/0800NightDev/UNESR_Horarios.git
cd UNESR_Horarios
```

Si ya tenías el repo clonado: `git pull origin main`. Después sigue la sección 5
para compilar el ejecutable de tu sistema.

Para configurar el repo desde cero en otro equipo:

```bash
cd UNESR_Horarios

git init
git remote add origin https://github.com/0800NightDev/UNESR_Horarios.git

git add .
git commit -m "Rewrite: Flask+pywebview, Supabase, pensum completo y horarios por carrera/dia"
git branch -M main
git push -u origin main
```

Si el repo ya tuviera historial, sustituye el `git init`/`remote add` por:

```bash
git clone https://github.com/0800NightDev/UNESR_Horarios.git
cd UNESR_Horarios
# copiar aquí el contenido de UNESR_TEST_BRANCH
git add . && git commit -m "Rewrite del sistema UNESR" && git push
```

> El `.env` está en `.gitignore`: tus credenciales **nunca** se suben.

---

## 8. Notas

- **Inventario de ambientes:** solo existen los 41 salones oficiales. La
  importación original traía 32 ambientes extra (PB, coordinaciones, aulas
  duplicadas, etc.) con 342 clases asignadas. Se reubicaron esas clases a
  salones oficiales con `scripts/normalizar_ambientes.py`, priorizando el mismo
  piso, sin crear solapes de ambiente y conservando las capacidades actuales;
  luego se borraron los 32 ambientes extra. El script tiene modo simulación
  (sin `--apply`) y guarda el plan de reasignación en `/tmp` para poder
  revertirlo. Las 440 asignaciones se conservaron; las colisiones pasaron de
  17 a 6 (todas preexistentes en salones oficiales).
- El pensum de las 9 carreras de Administración/Educación se tomó de
  `data/PLAN DE ESTUDIO 2024(1).xlsx` (hojas `ARRHH_2024`, `ARMF 2024`, etc.);
  el de los 3 PNF se extrajo de los PDFs en `uploads/` con `pdftotext -layout`.
  En el récord de Agroecología se descartan las filas "(Secundaria)" y los
  sufijos `-1`/`-2` para no duplicar unidades curriculares.
- Las colisiones que se ven al abrir el sistema vienen de la importación
  original con horas fijas: hay docentes con dos materias en el mismo día y
  hora, y ambientes repetidos. El generador **no las sobrescribe en silencio**:
  las deja visibles con su motivo y ofrece reasignación manual por clase en
  `/horarios`. Tras regenerar, pueden quedar bloques pendientes si no hay
  ambiente libre; el motivo se muestra en los avisos.
- No hay autenticación: el sistema está pensado para uso local/intranet.
- Si al reimportar el plan aparecía `409 duplicate key ... (Ética, Valores y
  Autobiografía, ...)`, estaba corregido: `_rest_val()` ya no envuelve entre
  comillas los valores con coma/paréntesis/punto en los filtros PostgREST.
  La búsqueda previa encuentra la fila y no se intenta insertarla dos veces.
- `migrate_to_supabase.py` importa el pensum y regenera asignaciones en SQLite
  **antes** de subir los datos, para no hacer miles de llamadas REST (antes se
  agotaba el tiempo de espera). Acepta `DB_BACKEND=auto` como origen.
- En modo `--server` el servidor corre en el hilo principal; con Supabase la
  primera petición tarda más y el sondeo de arranque ahora tiene margen
  suficiente (antes el programa se cerraba solo).
