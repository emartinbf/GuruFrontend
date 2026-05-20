@echo off
setlocal EnableDelayedExpansion
title Galicia Guru - Frontend Launcher

echo.
echo ========================================
echo   Galicia Guru - Frontend Launcher
echo ========================================
echo.

REM ----------------------------------------
REM 1. Verificar / instalar Python
REM ----------------------------------------
echo [1/4] Verificando Python...

set "PYTHON_EXE="
set "PYTHON_ARGS="
set "PYVER="

:CHECK_PYTHON
call :RESOLVE_PYTHON
set PYTHON_FOUND=%errorlevel%

if %PYTHON_FOUND% neq 0 (
    echo     Python no encontrado. Intentando instalar automaticamente...
    echo.

    REM --- Instalacion directa con winget ---
    echo     [winget] Instalando Python 3.11...
    winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% equ 0 (
        echo     [winget] Python instalado. Actualizando PATH de sesion...
        REM Refrescar PATH para que python.exe quede disponible en esta sesion
        for /f "tokens=*" %%P in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\") + \";\" + [System.Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%P"
        goto CHECK_PYTHON
    )

    echo.
    echo [ERROR] No se pudo instalar Python automaticamente con winget.
    echo.
    echo   Instalacion manual:
    echo   1. Verificar que winget este disponible y actualizado
    echo   2. Ejecutar: winget install --id Python.Python.3.11
    echo   3. Volver a ejecutar start.bat
    echo.
    pause
    exit /b 1
)

echo     Python encontrado: !PYVER!

REM ----------------------------------------
REM 2. Verificar version minima (3.9+)
REM ----------------------------------------
for /f "tokens=1,2 delims=." %%A in ("!PYVER!") do (
    set PYMAJOR=%%A
    set PYMINOR=%%B
)

if !PYMAJOR! lss 3 (
    echo.
    echo [ERROR] Python !PYVER! es demasiado antiguo. Se requiere Python 3.9 o superior.
    echo   Descargar desde: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
if !PYMAJOR! equ 3 if !PYMINOR! lss 9 (
    echo.
    echo [ERROR] Python !PYVER! es demasiado antiguo. Se requiere Python 3.9 o superior.
    echo   Descargar desde: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM ----------------------------------------
REM 3. Crear entorno virtual si no existe
REM ----------------------------------------
echo [2/4] Verificando entorno virtual...

if not exist "venv\" (
    echo     Entorno virtual no encontrado. Creando...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m venv venv
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] No se pudo crear el entorno virtual.
        echo   Verificar permisos de escritura en esta carpeta.
        echo.
        pause
        exit /b 1
    )
    echo     Entorno virtual creado exitosamente.
) else (
    echo     Entorno virtual encontrado.
)

REM ----------------------------------------
REM 4. Activar entorno virtual
REM ----------------------------------------
echo [3/4] Activando entorno virtual...
call venv\Scripts\activate
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] No se pudo activar el entorno virtual.
    echo   Intentar eliminar la carpeta venv\ y volver a ejecutar start.bat
    echo.
    pause
    exit /b 1
)

REM ----------------------------------------
REM 5. Instalar / verificar dependencias
REM ----------------------------------------
echo [4/4] Verificando dependencias (requirements.txt^)...
pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Error al instalar dependencias.
    echo   Verificar conexion a internet e intentar nuevamente.
    echo   Para ver el detalle del error ejecutar:
    echo     pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo     Dependencias OK.

REM ----------------------------------------
REM 6. Lanzar Streamlit
REM ----------------------------------------
echo.
echo ========================================
echo   Iniciando Streamlit...
echo ========================================
echo.
echo [+] Frontend:  http://localhost:8501
echo [+] Backend (debe estar corriendo): https://localhost:44321
echo.
echo [i] Presiona Ctrl+C para detener la aplicacion
echo.

streamlit run app.py

echo.
echo [i] Aplicacion detenida.
pause

goto :EOF

:RESOLVE_PYTHON
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "PYVER="

REM 1) Intentar con python en PATH
python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
    if /I not "!PYVER!"=="0.0.0.0" (
        set "PYTHON_EXE=python"
        exit /b 0
    )
)

REM 2) Intentar con py launcher
py -3.11 --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%V in ('py -3.11 --version 2^>^&1') do set "PYVER=%%V"
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.11"
    exit /b 0
)

py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%V in ('py -3 --version 2^>^&1') do set "PYVER=%%V"
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    exit /b 0
)

REM 3) Refrescar PATH de sesion por si hubo actualizaciones recientes
for /f "tokens=*" %%P in ('powershell -NoProfile -Command "[System.Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\") + \";\" + [System.Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%P"

python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
    if /I not "!PYVER!"=="0.0.0.0" (
        set "PYTHON_EXE=python"
        exit /b 0
    )
)

REM 4) Rutas comunes de instalacion de Python por usuario
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
    for /f "tokens=2" %%V in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PYVER=%%V"
    exit /b 0
)

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
    for /f "tokens=2" %%V in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PYVER=%%V"
    exit /b 0
)

if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python313\python.exe"
    for /f "tokens=2" %%V in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PYVER=%%V"
    exit /b 0
)

exit /b 1
