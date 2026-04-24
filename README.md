# ?? Galicia Guru - Frontend (Streamlit)

Frontend interactivo para el sistema de Base de Conocimiento Inteligente.

## ?? Quick Start

### **Requisitos:**
- Python 3.9 o superior
- Backend (GuruAPI) corriendo en `https://localhost:44321`

### **Instalación (Primera vez):**

```sh
# 1. Navegar a la carpeta del frontend
cd GuruFrontend

# 2. Crear entorno virtual (recomendado)
python -m venv venv

# 3. Activar entorno virtual
# En Windows:
venv\Scripts\activate
# En Mac/Linux:
source venv/bin/activate

# 4. Instalar dependencias
pip install -r requirements.txt
```

### **Ejecutar la Aplicación:**

```sh
# Asegúrate de estar en GuruFrontend/ con el venv activado

streamlit run app.py
```

**La aplicación se abrirá automáticamente en:** `http://localhost:8501`

**Asegúrate de que la API esté corriendo en:** `https://localhost:44321`

---

## ?? **Funcionalidades:**

### ?? **Búsqueda Inteligente**
- Buscar respuestas usando búsqueda semántica
- Ver score, threshold, y metadata
- Indicador de cache hit/miss

### ?? **Base de Conocimiento**
- Listar preguntas y respuestas activas
- Ver detalles completos de cada item
- Explorar la estructura de la KB

### ? **Preguntas Sin Respuesta**
- Ver preguntas que no obtuvieron respuesta adecuada
- Revisar respuestas generadas por IA
- Filtrar por estado (pendiente, respondida, cancelada)

### ?? **Gestión de Documentos**
- Subir PDFs, Word, Excel, PowerPoint
- Ver documentos procesados y sus chunks
- Eliminar documentos (MongoDB + Azure Search)
- Ver estadísticas de documentos

### ?? **Configuración (Sidebar)**
- Ver y actualizar threshold de búsqueda
- Limpiar caché de Redis
- Indexar versión activa o documentos
- Ver snapshot activo
- Estado de conexión con la API

---

## ??? **Cómo Funciona Streamlit:**

### **¿Qué es Streamlit?**
Streamlit es un framework de Python que convierte scripts Python en aplicaciones web interactivas **automáticamente**.

### **Arquitectura:**

```
????????????????????????????????????????????
?  Browser (http://localhost:8501)     ?
?  ??  ?
?  Streamlit Server         ?
?  (ejecuta app.py en cada interacción)    ?
?  ??        ?
?  HTTP Requests ?
?  ??                    ?
?  GuruAPI (https://localhost:44321)   ?
????????????????????????????????????????????
```

### **Flujo de Ejecución:**

1. **Ejecutas:** `streamlit run app.py`
2. **Streamlit:**
   - Inicia un servidor web en puerto 8501
   - Ejecuta `app.py` completamente
   - Genera HTML/JS automáticamente
   - Abre el browser

3. **Usuario interactúa** (click botón, escribe texto):
   - Streamlit **re-ejecuta app.py** completo
   - Actualiza solo lo que cambió en el browser
- Usa cache para optimizar

4. **Widgets generan UI:**
   ```python
   st.button("Click me")  # ? Botón HTML
   st.text_input("Query") # ? Input HTML
   st.dataframe(df)       # ? Tabla interactiva
 ```

### **Conceptos Clave:**

#### **1. Reruns (Re-ejecuciones):**
Cada vez que interactúas, **todo el script se vuelve a ejecutar**:

```python
# Esto se ejecuta CADA VEZ que tocas algo
st.title("Hola")

if st.button("Click"):
    # Esto solo se ejecuta si clickeaste
    st.write("Clickeaste!")
```

#### **2. Session State (Estado persistente):**
Para guardar datos entre reruns:

```python
if 'counter' not in st.session_state:
    st.session_state.counter = 0

if st.button("Incrementar"):
    st.session_state.counter += 1

st.write(f"Contador: {st.session_state.counter}")
```

#### **3. Widgets (Componentes de UI):**
```python
# Input de texto
query = st.text_input("Tu pregunta")

# Botón
if st.button("Buscar"):
    # hacer algo

# Selectbox
opcion = st.selectbox("Elige", ["A", "B", "C"])

# Slider
valor = st.slider("Valor", 0, 100, 50)

# File uploader
archivo = st.file_uploader("Sube PDF")

# Mostrar datos
st.write("Hola")
st.json({"key": "value"})
st.dataframe(df)
st.metric("Score", 0.92)
```

---

## ?? **Troubleshooting:**

### **Error: "ModuleNotFoundError: No module named 'streamlit'"**
```sh
# Asegúrate de activar el venv primero
venv\Scripts\activate
pip install -r requirements.txt
```

### **Error: "Error conectando con la API"**
```sh
# 1. Verifica que GuruAPI esté corriendo:
cd ../GuruAPI
dotnet run

# 2. Debe mostrar: "Now listening on: https://localhost:44321"
```

### **Warning: "InsecureRequestWarning"**
Es normal en desarrollo local con HTTPS autofirmado. El código ya lo maneja:
```python
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

### **La página no carga / está en blanco:**
```sh
# 1. Ctrl+C para detener Streamlit
# 2. Limpiar caché:
streamlit cache clear

# 3. Reiniciar:
streamlit run app.py
```

---

## ?? **Comandos Útiles:**

```sh
# Ver versión de Streamlit
streamlit --version

# Limpiar caché
streamlit cache clear

# Ejecutar en puerto diferente
streamlit run app.py --server.port 8502

# Ver configuración
streamlit config show

# Modo debug
streamlit run app.py --logger.level=debug
```

---

## ?? **Personalización:**

### **Cambiar Tema:**
Crear archivo `.streamlit/config.toml`:

```toml
[theme]
primaryColor = "#1f77b4"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"
font = "sans serif"
```

### **Cambiar Puerto:**
```sh
streamlit run app.py --server.port 9000
```

---

## ?? **Estructura del Código:**

```python
# app.py está organizado en:

1. Imports y Configuración
   ?? st.set_page_config()

2. CSS Personalizado
   ?? st.markdown("<style>...")

3. Header y Título

4. Tabs Principales
   ?? Tab 1: Búsqueda
   ?? Tab 2: Base de Conocimiento
   ?? Tab 3: Preguntas Sin Respuesta
 ?? Tab 4: Documentos

5. Sidebar
   ?? Configuración
   ?? Cache
   ?? Indexación
   ?? Status

6. Footer
```

---

## ?? **Workflow de Desarrollo:**

### **1. Iniciar Backend:**
```sh
cd GuruAPI
dotnet run
```

### **2. Iniciar Frontend (otra terminal):**
```sh
cd GuruFrontend
venv\Scripts\activate  # Windows
streamlit run app.py
```

### **3. Desarrollo:**
- Edita `app.py`
- Streamlit detecta cambios automáticamente
- Click "Rerun" en el browser (aparece arriba a la derecha)

---

## ?? **Próximos Pasos:**

- [ ] Agregar autenticación (opcional)
- [ ] Agregar gráficos de métricas
- [ ] Exportar datos a CSV
- [ ] Modo dark/light
- [ ] Deploy a Streamlit Cloud

---

## ?? **Links Útiles:**

- **Streamlit Docs:** https://docs.streamlit.io
- **API Cheat Sheet:** https://docs.streamlit.io/library/cheatsheet
- **Gallery:** https://streamlit.io/gallery
- **GuruAPI Swagger:** https://localhost:44321/swagger

---

**¿Necesitas ayuda?** Revisa los logs en la terminal donde ejecutaste `streamlit run app.py`
