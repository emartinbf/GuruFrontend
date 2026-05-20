# Galicia Guru - Frontend (Streamlit)

Frontend interactivo para el sistema de Base de Conocimiento Inteligente.

---

## Inicio Rapido (Windows)

### Paso 1 - Instalar Python

> **`start.bat` intenta instalar Python automaticamente** si no lo detecta.
> Primero prueba via `winget` (Windows 10/11), y si falla descarga el instalador directamente desde python.org.
> En la mayoria de los casos no hace falta hacer nada manual.

Si la instalacion automatica falla por algun motivo:

1. Ir a **https://www.python.org/downloads/**
2. Descargar **Python 3.11.x** (o cualquier version 3.9+)
3. Ejecutar el instalador y **tildar "Add Python to PATH"** antes de instalar
4. Verificar la instalacion abriendo una terminal nueva:

```
python --version
```

Debe mostrar algo como: `Python 3.11.9`

> **Importante (Windows):** Si el comando abre el Microsoft Store en lugar de mostrar la version,
> ir a `Configuracion > Aplicaciones > Configuracion avanzada de aplicaciones > Alias de ejecucion de aplicaciones`
> y deshabilitar los alias de `python.exe` y `python3.exe`.

---

### Paso 2 - Iniciar la aplicacion

Simplemente hacer doble click en `start.bat` o ejecutarlo desde la terminal:

```bat
cd GuruFrontend
start.bat
```

El script automaticamente:
- Verifica que Python este instalado y sea version 3.9 o superior
- Crea el entorno virtual (`venv\`) si no existe
- Instala todas las dependencias de `requirements.txt`
- Lanza la aplicacion Streamlit

La aplicacion queda disponible en: **http://localhost:8501**

---

### Paso 3 - Iniciar el Backend

El frontend necesita que la API este corriendo. En **otra terminal**:

```bat
cd GuruAPI
dotnet run
```

La API debe mostrar: `Now listening on: https://localhost:44321`

---

## Dependencias

Definidas en `requirements.txt`:

| Paquete    | Version    | Uso                                  |
|------------|------------|--------------------------------------|
| streamlit  | 1.36.0     | Framework de UI web                  |
| requests   | 2.31.0     | Llamadas HTTP a la API               |
| urllib3    | 2.2.0      | Cliente HTTP (deshabilita warnings)  |
| pillow     | >=9.0,<11  | Procesamiento de imagenes            |

---

## Funcionalidades

### Busqueda Inteligente
- Buscar respuestas usando busqueda semantica
- Ver score, threshold y metadata
- Indicador de cache hit/miss

### Base de Conocimiento
- Listar preguntas y respuestas activas
- Ver detalles completos de cada item

### Preguntas Sin Respuesta
- Ver preguntas que no obtuvieron respuesta adecuada
- Revisar respuestas generadas por IA
- Filtrar por estado (pendiente, respondida, cancelada)

### Gestion de Documentos
- Subir PDFs, Word, Excel, PowerPoint
- Ver documentos procesados y sus chunks
- Eliminar documentos (MongoDB + Azure Search)
- Ver estadisticas de documentos

### Configuracion (Sidebar)
- Ver y actualizar threshold de busqueda
- Limpiar cache de Redis
- Indexar version activa o documentos
- Ver snapshot activo
- Estado de conexion con la API

---

## Troubleshooting

### "Python no esta instalado o no esta en el PATH"
Seguir el Paso 1 de este README. Asegurarse de tildar "Add Python to PATH" durante la instalacion.

### "Se detecto el stub de Python de Microsoft Store"
Ir a `Configuracion > Aplicaciones > Alias de ejecucion de aplicaciones` y deshabilitar los alias de `python.exe` y `python3.exe`. Luego instalar Python desde https://www.python.org/downloads/

### "Error conectando con la API"
Verificar que GuruAPI este corriendo en `https://localhost:44321`.
Seguir el Paso 3 de este README.

### "ModuleNotFoundError: No module named 'streamlit'"
El entorno virtual no esta activo. Ejecutar `start.bat` que lo activa automaticamente, o manualmente:
```bat
venv\Scripts\activate
pip install -r requirements.txt
```

### La pagina no carga o esta en blanco
```bat
REM Detener Streamlit con Ctrl+C, luego:
streamlit cache clear
streamlit run app.py
```

---

## Comandos utiles

```bat
REM Ver version de Streamlit
streamlit --version

REM Limpiar cache
streamlit cache clear

REM Ejecutar en puerto diferente
streamlit run app.py --server.port 8502

REM Modo debug
streamlit run app.py --logger.level=debug
```

---

## Estructura del proyecto

```
GuruFrontend/
|-- app.py              # Aplicacion principal (UI Streamlit)
|-- requirements.txt    # Dependencias Python
|-- runtime.txt         # Version de Python para deployment (3.11.9)
|-- start.bat           # Lanzador Windows con validaciones automaticas
|-- README.md           # Este archivo
+-- .streamlit/         # Configuracion de Streamlit (tema, etc.)
```

---

## Workflow de desarrollo

```
Terminal 1 (Backend):
  cd GuruAPI
  dotnet run

Terminal 2 (Frontend):
  cd GuruFrontend
  start.bat
```

Streamlit detecta cambios en `app.py` automaticamente.
Hacer click en "Rerun" en el browser (boton en la esquina superior derecha) para refrescar.
