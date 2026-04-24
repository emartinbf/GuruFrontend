# Configuración de Ambientes - API_URL

## Local (Desarrollo)

Cuando ejecutas en local, la app usa automáticamente:

```
https://localhost:44321/api
```

## Streamlit Cloud (Producción)

Para configurar en Streamlit Cloud:

1. **Ve a tu app en Streamlit Cloud** (https://share.streamlit.io/)
2. **Haz clic en los 3 puntos** (⋮) → **Settings**
3. **Abre la sección "Secrets"**
4. **Pega esto en el editor:**

```toml
api_url = "https://poc-guru-hdf0gvb2a2f4ehgf.eastus-01.azurewebsites.net/"
```

5. **Haz clic en "Save"**

La app se reiniciará automáticamente con la nueva configuración.

---

## Cómo funciona

- **En local**: Intenta leer `secrets.toml` (fichero local que no se versiona), si falla usa `https://localhost:44321/api`
- **En Streamlit Cloud**: Lee los secrets configurados en la interfaz web de Streamlit

## .gitignore

Asegúrate de que `.streamlit/secrets.toml` esté en `.gitignore` para no versionar secretos:

```
.streamlit/secrets.toml
```
