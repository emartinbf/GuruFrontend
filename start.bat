@echo off
echo ========================================
echo   Galicia Guru - Frontend Launcher
echo ========================================
echo.

REM Verificar si existe venv
if not exist "venv\" (
    echo [!] Entorno virtual no encontrado.
  echo [i] Creando entorno virtual...
    python -m venv venv
    echo.
)

echo [i] Activando entorno virtual...
call venv\Scripts\activate

echo [i] Verificando dependencias...
pip install -r requirements.txt --quiet

echo.
echo ========================================
echo   Iniciando Streamlit...
echo ========================================
echo.
echo [+] Frontend: http://localhost:8501
echo [+] Backend (debe estar corriendo): https://localhost:44321
echo.
echo [i] Presiona Ctrl+C para detener
echo.

streamlit run app.py

pause
