import streamlit as st
import requests
from datetime import datetime, time
from urllib.parse import quote
import os

st.set_page_config(page_title="Galicia Guru", page_icon=":robot:", layout="wide")

# Obtener API_URL según el ambiente
try:
    # En Streamlit Cloud, usar el secret configurado
    API_URL = st.secrets["api_url"]
except (FileNotFoundError, KeyError):
    # En local, usar la URL de localhost
    API_URL = os.getenv("API_URL", "https://localhost:44321/api")

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def api_request(method, path, **kwargs):
    try:
        return requests.request(method, f"{API_URL}{path}", verify=False, timeout=1500000, **kwargs)
    except Exception as ex:
        st.error(f"Error de conexion: {str(ex)}")
        return None


def render_error_response(response):
    try:
        detail = response.json()
        st.error(f"Error {response.status_code}: {detail}")
    except Exception:
        st.error(f"Error {response.status_code}: {response.text}")


def load_respuestas_catalog(force_refresh=False):
    if force_refresh or "respuestas_catalog" not in st.session_state:
        response = api_request("GET", "/kb/respuestas")
        if response and response.status_code == 200:
            st.session_state.respuestas_catalog = response.json()
        elif response:
            render_error_response(response)
            st.session_state.respuestas_catalog = []
        else:
            st.session_state.respuestas_catalog = []

    return st.session_state.get("respuestas_catalog", [])


def resolve_respuesta_id(respuesta_id_input, answer_key_input):
    respuesta_id = (respuesta_id_input or "").strip()
    answer_key = (answer_key_input or "").strip()

    if answer_key:
        catalog = load_respuestas_catalog()
        match = next(
            (r for r in catalog if (r.get("answerKey") or "").strip().lower() == answer_key.lower()),
            None,
        )
        if not match:
            return None, f"No existe una respuesta con answerKey '{answer_key}'"
        return match.get("id"), None

    if respuesta_id:
        return respuesta_id, None

    return None, None


def load_snapshots_list(force_refresh=False):
    if force_refresh or "snapshots_list" not in st.session_state:
        response = api_request("GET", "/versioning/snapshots")
        if response and response.status_code == 200:
            st.session_state.snapshots_list = response.json() or []
        elif response:
            render_error_response(response)
            st.session_state.snapshots_list = []
        else:
            st.session_state.snapshots_list = []

    return st.session_state.get("snapshots_list", [])


def get_active_snapshot_version():
    snapshots = load_snapshots_list()
    for snapshot in snapshots:
        if snapshot.get("isActive") or snapshot.get("activa"):
            return snapshot.get("version")
    return None


def get_latest_snapshot_version():
    snapshots = load_snapshots_list()
    if not snapshots:
        return None

    def snapshot_date(snapshot):
        raw_date = (
            snapshot.get("fechaCreacion")
            or snapshot.get("createdAt")
            or snapshot.get("fecha_creacion")
            or ""
        )
        if not raw_date:
            return datetime.min

        try:
            return datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return datetime.min

    latest_snapshot = max(snapshots, key=snapshot_date)
    return latest_snapshot.get("version")


def format_snapshot_option(version, active_version=None):
    if not version:
        return ""
    if version == active_version:
        return f"{version} (ACTIVA)"
    return version

st.title("Galicia Guru - Sistema de Conocimiento")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Busqueda", "Base Conocimiento", "Documentos", "Metricas", "Testing"])

with tab1:
    st.header("Busqueda Inteligente")
    query = st.text_input("Tu pregunta:", placeholder="Como veo mi saldo?")

    if "search_result" not in st.session_state:
        st.session_state.search_result = None

    if st.button("Buscar", type="primary") and query:
        st.session_state.search_result = None
        with st.spinner("Buscando..."):
            response = api_request("GET", "/guru/search", params={"query": query})
        if response is not None and response.status_code == 200:
            data = response.json()
            if "error" in data:
                st.session_state.search_result = {"type": "no_answer", "msg": data["error"]}
            else:
                st.session_state.search_result = {"type": "ok", "data": data}
        elif response is not None and response.status_code in (404, 400, 422):
            try:
                msg = response.json().get("error", "No se encontro respuesta adecuada")
            except Exception:
                msg = "No se encuentro respuesta adecuada"
            st.session_state.search_result = {"type": "no_answer", "msg": msg}
        elif response is not None:
            st.session_state.search_result = {"type": "error", "code": response.status_code, "text": response.text}
        else:
            st.session_state.search_result = {"type": "no_answer", "msg": "No se pudo conectar con la API"}

    result = st.session_state.get("search_result")
    if result:
        if result["type"] == "ok":
            data = result["data"]
            debug_data = data.get('debug', {})
            st.success("Respuesta encontrada")
            st.info(data['answer'])

            with st.expander("Ver detalle del resultado"):
                detail_col1, detail_col2, detail_col3 = st.columns(3)
                with detail_col1:
                    st.write("**Answer ID:**", data.get("answerId") or "N/A")
                    st.write("**Version:**", data.get("version") or "N/A")
                with detail_col2:
                    st.write("**Score:**", data.get("score") if data.get("score") is not None else "N/A")
                    st.write("**Query Hash:**", debug_data.get("queryHash") or "N/A")
                with detail_col3:
                    st.write("**Query original:**", debug_data.get("originalQuery") or data.get("query") or "N/A")
                    st.write("**Cache Hit:**", debug_data.get("cacheHit") if debug_data.get("cacheHit") is not None else "N/A")

                if debug_data:
                    st.markdown("**Debug payload**")
                    st.json(debug_data)
            
            # ✅ BOTONES DE FEEDBACK
            st.markdown("---")
            st.markdown("**¿Esta respuesta fue útil?**")
            col_feedback1, col_feedback2, col_feedback3 = st.columns([1, 1, 4])
    
            with col_feedback1:
                if st.button("👍 Útil", key="btn_positive_feedback"):
                    feedback_payload = {
                        "queryHash": debug_data.get('queryHash', ''),
                        "originalQuery": debug_data.get('originalQuery') or data.get('query'),
                        "answerId": data.get('answerId'),
                        "score": data.get('score'),
                        "feedbackType": "positive",
                        "version": data.get('version')
                    }
                    feedback_response = api_request("POST", "/quality/feedback", json=feedback_payload)
                    if feedback_response and feedback_response.status_code == 200:
                        st.success("✅ Gracias por tu feedback!")
                    elif feedback_response:
                        st.error("Error enviando feedback")
    
            with col_feedback2:
                if st.button("👎 No útil", key="btn_negative_feedback"):
                    st.session_state.show_feedback_form = True
       
            # Formulario de feedback negativo con comentario
            if st.session_state.get("show_feedback_form", False):
                with st.form("form_negative_feedback"):
                    feedback_comment = st.text_area("¿Qué estuvo mal?", placeholder="Opcional: ayúdanos a mejorar")
                    submit_negative = st.form_submit_button("Enviar feedback")
                    
                    if submit_negative:
                        feedback_payload = {
                            "queryHash": debug_data.get('queryHash', ''),
                            "originalQuery": debug_data.get('originalQuery') or data.get('query'),
                            "answerId": data.get('answerId'),
                            "score": data.get('score'),
                            "feedbackType": "negative",
                            "comment": feedback_comment or None,
                            "version": data.get('version')
                        }
                        feedback_response = api_request("POST", "/quality/feedback", json=feedback_payload)
                        if feedback_response and feedback_response.status_code == 200:
                            st.success("✅ Gracias por tu feedback!")
                            st.session_state.show_feedback_form = False
                            st.rerun()
                        elif feedback_response:
                            st.error("Error enviando feedback")

            st.markdown("---")
        elif result["type"] == "no_answer":
            st.warning(result["msg"])
            st.info("La pregunta se guardo para revision")
        elif result["type"] == "error":
            st.error(f"Error {result['code']}: {result['text']}")

with tab2:
    st.header("Base de Conocimiento")

    kb_tab1, kb_tab2, kb_tab3, kb_tab4 = st.tabs(["Preguntas", "Respuestas", "Snapshots", "Sin Responder"])

    with kb_tab1:
        st.subheader("Preguntas")

        if "preguntas" not in st.session_state:
            st.session_state.preguntas = []

        if st.button("Listar todas las preguntas", key="btn_list_all_preguntas"):
            response = api_request("GET", "/kb/preguntas")
            if response and response.status_code == 200:
                st.session_state.preguntas = response.json()
                st.success(f"{len(st.session_state.preguntas)} preguntas activas")
            elif response:
                render_error_response(response)

        respuestas_catalog = load_respuestas_catalog()
        answer_key_by_respuesta_id = {
            r.get("id"): r.get("answerKey")
            for r in respuestas_catalog
            if r.get("id")
        }

        if st.session_state.get("preguntas", []):
            st.dataframe(
                [
                    {
                        "id": p.get("id"),
                        "texto": p.get("texto"),
                        "respuestaId": p.get("respuestaId"),
                        "answerKey": answer_key_by_respuesta_id.get(p.get("respuestaId"), "N/A"),
                        "activa": p.get("activa")
                    }
                    for p in st.session_state.get("preguntas", [])
                ],
                use_container_width=True
            )

        st.markdown("---")
        st.markdown("**Agregar pregunta**")
        with st.form("form_add_pregunta"):
            new_pregunta_texto = st.text_area("Texto pregunta")
            col_add_1, col_add_2 = st.columns(2)
            with col_add_1:
                new_pregunta_respuesta_id = st.text_input("Respuesta ID (opcional)")
            with col_add_2:
                new_pregunta_answer_key = st.text_input(
                    "Answer Key (opcional)",
                    help="Si completás este campo, se resuelve automáticamente la respuesta por answerKey.",
                )
            new_pregunta_id_padre = st.text_input("ID Padre (opcional)")
            add_pregunta = st.form_submit_button("Agregar pregunta")
            if add_pregunta:
                resolved_respuesta_id, resolution_error = resolve_respuesta_id(
                    new_pregunta_respuesta_id,
                    new_pregunta_answer_key,
                )
                if resolution_error:
                    st.warning(resolution_error)
                elif not resolved_respuesta_id:
                    st.warning("Debes ingresar Respuesta ID o Answer Key")
                else:
                    payload = {
                        "texto": new_pregunta_texto,
                        "respuestaId": resolved_respuesta_id,
                        "idPadre": new_pregunta_id_padre or None
                    }
                    response = api_request("POST", "/kb/preguntas", json=payload)
                    if response and response.status_code == 200:
                        st.success("Pregunta creada")
                        st.rerun()
                    elif response:
                        render_error_response(response)

        st.markdown("---")
        st.markdown("**Editar pregunta**")
        pregunta_options = st.session_state.get("preguntas", [])
        pregunta_map = {
            f"{p.get('id')} - {p.get('texto', '')[:80]}": p
            for p in pregunta_options
        }
        selected_pregunta_label = st.selectbox(
            "Seleccionar pregunta",
            [""] + list(pregunta_map.keys()),
            key="select_edit_pregunta"
        )

        with st.form("form_edit_pregunta"):
            default_pregunta_text = ""
            default_pregunta_respuesta = ""
            default_pregunta_answer_key = ""
            selected_pregunta_id = ""

            if selected_pregunta_label:
                selected_pregunta = pregunta_map[selected_pregunta_label]
                selected_pregunta_id = selected_pregunta.get("id", "")
                default_pregunta_text = selected_pregunta.get("texto", "")
                default_pregunta_respuesta = selected_pregunta.get("respuestaId", "")
                default_pregunta_answer_key = answer_key_by_respuesta_id.get(default_pregunta_respuesta, "")

            edit_pregunta_texto = st.text_area("Nuevo texto", value=default_pregunta_text)
            col_edit_1, col_edit_2 = st.columns(2)
            with col_edit_1:
                edit_pregunta_respuesta = st.text_input(
                    "Nuevo respuestaId (opcional)",
                    value=default_pregunta_respuesta,
                )
            with col_edit_2:
                edit_pregunta_answer_key = st.text_input(
                    "Nuevo answerKey (opcional)",
                    value=default_pregunta_answer_key,
                )

            edit_pregunta_submit = st.form_submit_button("Guardar cambios pregunta")

            if edit_pregunta_submit:
                if not selected_pregunta_id:
                    st.warning("Primero lista y selecciona una pregunta")
                else:
                    resolved_respuesta_id, resolution_error = resolve_respuesta_id(
                        edit_pregunta_respuesta,
                        edit_pregunta_answer_key,
                    )
                    if resolution_error:
                        st.warning(resolution_error)
                    else:
                            payload = {
                                "texto": edit_pregunta_texto,
                                "respuestaId": resolved_respuesta_id or None
                            }
                            response = api_request("PUT", f"/kb/preguntas/{selected_pregunta_id}", json=payload)
                            if response and response.status_code == 200:
                                st.success("Pregunta actualizada")
                                st.rerun()
                            elif response:
                                render_error_response(response)

        st.markdown("---")
        st.markdown("**Eliminar pregunta**")
        delete_pregunta_label = st.selectbox(
            "Seleccionar pregunta a eliminar",
            [""] + list(pregunta_map.keys()),
            key="select_delete_pregunta"
        )
        if st.button("Eliminar pregunta", key="btn_delete_pregunta"):
            if not delete_pregunta_label:
                st.warning("Selecciona una pregunta")
            else:
                pregunta_id = pregunta_map[delete_pregunta_label].get("id")
                response = api_request("DELETE", f"/kb/preguntas/{pregunta_id}")
                if response and response.status_code == 200:
                    st.success("Pregunta deshabilitada")
                    st.rerun()
                elif response:
                    render_error_response(response)

    with kb_tab2:
        st.subheader("Respuestas")

        if "respuestas" not in st.session_state:
            st.session_state.respuestas = []

        if st.button("Listar todas las respuestas", key="btn_list_all_respuestas"):
            response = api_request("GET", "/kb/respuestas")
            if response and response.status_code == 200:
                st.session_state.respuestas = response.json()
                st.session_state.respuestas_catalog = response.json()
                st.success(f"{len(st.session_state.respuestas)} respuestas activas")
            elif response:
                render_error_response(response)

        if st.session_state.get("respuestas", []):
            st.dataframe(
                [
                    {
                        "id": r.get("id"),
                        "answerKey": r.get("answerKey", "N/A"),
                        "texto": r.get("texto")[:100] + "..." if len(r.get("texto", "")) > 100 else r.get("texto"),
                        "activa": r.get("activa")
                    }
                    for r in st.session_state.get("respuestas", [])
                ],
                use_container_width=True
            )

        st.markdown("---")
        st.markdown("**Agregar respuesta**")
        with st.form("form_add_respuesta"):
            new_respuesta_answer_key = st.text_input(
                "Answer Key (opcional)",
                placeholder="SALDO_CONSULTA",
                help="Código inmutable para identificar la respuesta. Si no se especifica, se genera automáticamente.",
            )
            new_respuesta_texto = st.text_area("Texto respuesta")
            new_respuesta_id_padre = st.text_input("ID Padre (opcional)")
            add_respuesta = st.form_submit_button("Agregar respuesta")
            if add_respuesta:
                payload = {
                    "texto": new_respuesta_texto,
                    "answerKey": new_respuesta_answer_key or None,
                    "idPadre": new_respuesta_id_padre or None
                }
                response = api_request("POST", "/kb/respuestas", json=payload)
                if response and response.status_code == 200:
                    result = response.json()
                    st.success(f"Respuesta creada - AnswerKey: {result.get('answerKey', 'N/A')}")
                    st.json(result)
                    st.rerun()
                elif response:
                    render_error_response(response)

        st.markdown("---")
        st.markdown("**Editar respuesta**")
        respuesta_options = st.session_state.get("respuestas", [])
        respuesta_map = {
            f"{r.get('id')} [{r.get('answerKey', 'N/A')}] - {r.get('texto', '')[:60]}": r
            for r in respuesta_options
        }
        selected_respuesta_label = st.selectbox(
            "Seleccionar respuesta",
            [""] + list(respuesta_map.keys()),
            key="select_edit_respuesta"
        )

        with st.form("form_edit_respuesta"):
            default_respuesta_text = ""
            default_respuesta_answer_key = ""
            selected_respuesta_id = ""

            if selected_respuesta_label:
                selected_respuesta = respuesta_map[selected_respuesta_label]
                selected_respuesta_id = selected_respuesta.get("id", "")
                default_respuesta_text = selected_respuesta.get("texto", "")
                default_respuesta_answer_key = selected_respuesta.get("answerKey", "")

            st.info(f"AnswerKey actual: **{default_respuesta_answer_key or 'Sin key'}** (no se puede modificar)")
            edit_respuesta_texto = st.text_area("Nuevo texto respuesta", value=default_respuesta_text)
            edit_respuesta_submit = st.form_submit_button("Guardar cambios respuesta")

            if edit_respuesta_submit:
                if not selected_respuesta_id:
                    st.warning("Primero lista y selecciona una respuesta")
                else:
                    payload = {"texto": edit_respuesta_texto}
                    response = api_request("PUT", f"/kb/respuestas/{selected_respuesta_id}", json=payload)
                    if response and response.status_code == 200:
                        result = response.json()
                        if result.get("message") == "Nueva version creada":
                            st.success(f"Nueva versión creada - ID: {result.get('nuevaRespuestaId')}")
                            st.info(f"AnswerKey se mantuvo: {default_respuesta_answer_key}")
                            st.json(result)
                        else:
                            st.success("Respuesta actualizada")
                        st.rerun()
                    elif response:
                        render_error_response(response)

        st.markdown("---")
        st.markdown("**Eliminar respuesta**")
        delete_respuesta_label = st.selectbox(
            "Seleccionar respuesta a eliminar",
            [""] + list(respuesta_map.keys()),
            key="select_delete_respuesta"
        )
        if st.button("Eliminar respuesta", key="btn_delete_respuesta"):
            if not delete_respuesta_label:
                st.warning("Selecciona una respuesta")
            else:
                respuesta_id = respuesta_map[delete_respuesta_label].get("id")
                response = api_request("DELETE", f"/kb/respuestas/{respuesta_id}")
                if response and response.status_code == 200:
                    st.success("Respuesta deshabilitada")
                    st.rerun()
                elif response:
                    render_error_response(response)

    with kb_tab3:
        st.subheader("Snapshots")

        if st.button("Ver snapshot actual", key="btn_active_snapshot"):
            response = api_request("GET", "/versioning/snapshots/active")
            if response and response.status_code == 200:
                snapshot = response.json()
                st.success(f"Snapshot activo: {snapshot.get('version')}")
                st.json(snapshot)
            elif response and response.status_code == 404:
                st.info("No hay snapshot activo")
            elif response:
                render_error_response(response)

        st.markdown("---")
        st.markdown("**Activar snapshot existente**")
        snapshots = load_snapshots_list(force_refresh=True)
        snapshot_versions = [s.get("version") for s in snapshots if s.get("version")]
        active_snapshot_version = get_active_snapshot_version()
        latest_snapshot_version = get_latest_snapshot_version()

        if snapshot_versions:
            try:
                default_activate_idx = (
                    snapshot_versions.index(latest_snapshot_version)
                    if latest_snapshot_version in snapshot_versions
                    else 0
                )
            except (ValueError, IndexError):
                default_activate_idx = 0

            selected_snapshot_version = st.selectbox(
                "Seleccionar versión a activar",
                snapshot_versions,
                index=default_activate_idx,
                key="select_snapshot_to_activate",
                format_func=lambda v: format_snapshot_option(v, active_snapshot_version),
            )

            if st.button("Activar", key="btn_activate_snapshot", type="primary"):
                encoded_version = quote(selected_snapshot_version, safe='')
                response = api_request("POST", f"/versioning/snapshots/{encoded_version}/activate")
                if response and response.status_code == 200:
                    st.success(f"Snapshot activado: {selected_snapshot_version}")
                    st.session_state.pop("snapshots_list", None)
                    st.rerun()
                elif response:
                    render_error_response(response)
        else:
            st.info("No hay snapshots disponibles para activar")

        st.markdown("---")
        st.markdown("**Crear snapshot**")
        with st.form("form_create_snapshot"):
            snapshot_version = st.text_input("Version", placeholder="v2.1.0")
            snapshot_set_active = st.checkbox("Activar luego de crear", value=True)
            snapshot_ids_raw = st.text_area(
                "IDs de pregunta (opcional, uno por linea)",
                placeholder="Si lo dejas vacio incluye todas las preguntas activas"
            )
            create_snapshot = st.form_submit_button("Crear snapshot")

            if create_snapshot:
                pregunta_ids = [
                    line.strip()
                    for line in snapshot_ids_raw.splitlines()
                    if line.strip()
                ]
                payload = {
                    "version": snapshot_version,
                    "setAsActive": snapshot_set_active
                }
                if pregunta_ids:
                    payload["preguntaIds"] = pregunta_ids

                response = api_request("POST", "/versioning/snapshots", json=payload)
                if response and response.status_code == 200:
                    st.success("Snapshot creado")
                    st.json(response.json())
                elif response:
                    render_error_response(response)

    with kb_tab4:
        st.subheader("Preguntas sin responder")

        if "pending_questions" not in st.session_state:
            st.session_state.pending_questions = []

        if st.button("Ver pendientes", key="btn_pending_questions"):
            response = api_request("GET", "/kb/unanswered-questions/pending")
            if response and response.status_code == 200:
                st.session_state.pending_questions = response.json()
                st.success(f"{len(st.session_state.pending_questions)} pendientes")
            elif response:
                render_error_response(response)

        if st.session_state.get("pending_questions", []):
            for q in st.session_state.get("pending_questions", []):
                question_text = q.get("question") or q.get("pregunta") or q.get("query") or "(sin texto)"
                with st.expander(f"{q.get('id')} - {question_text[:90]}"):
                    st.json(q)

            pending_map = {
                f"{q.get('id')} - {(q.get('question') or q.get('pregunta') or q.get('query') or '')[:80]}": q
                for q in st.session_state.get("pending_questions", [])
            }

            selected_pending = st.selectbox(
                "Seleccionar pendiente a resolver",
                [""] + list(pending_map.keys()),
                key="select_pending_question"
            )

            with st.form("form_resolve_pending"):
                pending_usuario = st.text_input("Usuario", value="admin")
                pending_estado = st.selectbox("Estado", ["respondida", "cancelada"])
                pending_respuesta_final = st.text_area("Respuesta final (si respondida)")
                pending_observaciones = st.text_area("Observaciones")
                submit_pending = st.form_submit_button("Guardar resolucion")

                if submit_pending:
                    if not selected_pending:
                        st.warning("Selecciona una pregunta pendiente")
                    else:
                        pending_id = pending_map[selected_pending].get("id")
                        payload = {
                            "estado": pending_estado,
                            "usuario": pending_usuario,
                            "respuestaFinal": pending_respuesta_final or None,
                            "observaciones": pending_observaciones or None
                        }
                        response = api_request("PUT", f"/kb/unanswered-questions/{pending_id}/response", json=payload)
                        if response and response.status_code == 200:
                            st.success("Pendiente actualizado")
                            st.json(response.json())
                            st.rerun()
                        elif response:
                            render_error_response(response)
        else:
            st.info("No hay pendientes cargados. Usa 'Ver pendientes'.")

with tab3:
    st.header("Documentos")
    
    if "documentos" not in st.session_state:
        st.session_state.documentos = []
    
    uploaded_file = st.file_uploader("Subir PDF/Word", type=['pdf', 'docx'])
    
    if uploaded_file and st.button("Procesar"):
        with st.spinner(f"Procesando {uploaded_file.name}..."):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
            response = api_request("POST", "/documents/upload", files=files)
            
            if response and response.status_code == 200:
                result = response.json()
                st.success("Documento procesado")
                st.write(f"Chunks creados: {result['chunksCreated']}")
                st.write(f"Paginas: {result['totalPages']}")
                st.write(f"Tiempo: {result['processingTimeMs']}ms")
                st.session_state.documentos = []
            elif response:
                render_error_response(response)
    
    if st.button("Listar Documentos"):
        response = api_request("GET", "/documents")
        if response and response.status_code == 200:
            st.session_state.documentos = response.json()
        elif response:
            render_error_response(response)
    
    docs = st.session_state.get("documentos", [])
    if docs:
        st.success(f"{len(docs)} documentos")
        for doc in docs:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"{doc['fileName']} ({doc['totalChunks']} chunks)")
            with col2:
                if st.button("Eliminar", key=f"del_{doc['fileName']}"):
                    encoded_filename = quote(doc['fileName'], safe='')
                    del_resp = api_request("DELETE", f"/documents/{encoded_filename}")
                    if del_resp and del_resp.status_code == 200:
                        st.success("Documento eliminado")
                        st.session_state.documentos = [d for d in st.session_state.documentos if d['fileName'] != doc['fileName']]
                        st.rerun()
                    elif del_resp:
                        render_error_response(del_resp)

with tab4:
    st.header("Metricas de Busqueda")

    if "metrics_payload" not in st.session_state:
        st.session_state.metrics_payload = {}

    colf1, colf2, colf3 = st.columns([1, 1, 1])
    with colf1:
        metrics_from_date = st.date_input("Desde", value=datetime.now().date())
    with colf2:
        metrics_to_date = st.date_input("Hasta", value=datetime.now().date())
    with colf3:
        metrics_recent_limit = st.number_input("Ultimos registros", min_value=10, max_value=1000, value=100, step=10)

    if st.button("Actualizar metricas", type="primary", key="btn_refresh_metrics"):
        from_dt = datetime.combine(metrics_from_date, time.min).isoformat()
        to_dt = datetime.combine(metrics_to_date, time.max).isoformat()
        params_range = {"from": from_dt, "to": to_dt}

        summary_resp = api_request("GET", "/Metrics/summary", params=params_range)
        perf_resp = api_request("GET", "/Metrics/performance", params=params_range)
        dist_resp = api_request("GET", "/Metrics/distribution", params=params_range)
        recent_resp = api_request("GET", "/Metrics/recent", params={"limit": int(metrics_recent_limit)})

        if summary_resp and summary_resp.status_code == 200:
            st.session_state.metrics_payload["summary"] = summary_resp.json()
        elif summary_resp:
            render_error_response(summary_resp)

        if perf_resp and perf_resp.status_code == 200:
            st.session_state.metrics_payload["performance"] = perf_resp.json()
        elif perf_resp:
            render_error_response(perf_resp)

        if dist_resp and dist_resp.status_code == 200:
            st.session_state.metrics_payload["distribution"] = dist_resp.json()
        elif dist_resp:
            render_error_response(dist_resp)

        if recent_resp and recent_resp.status_code == 200:
            st.session_state.metrics_payload["recent"] = recent_resp.json()
        elif recent_resp:
            render_error_response(recent_resp)

    metrics_payload = st.session_state.get("metrics_payload", {})
    summary = metrics_payload.get("summary", {})
    performance = metrics_payload.get("performance", {})
    distribution = metrics_payload.get("distribution", {})
    recent = metrics_payload.get("recent", [])

    if not summary and not performance:
        st.info("Presiona 'Actualizar metricas' para cargar datos")
    else:
        st.subheader("Contadores principales")
        total_searches = performance.get("totalSearches", summary.get("totalSearches", 0))
        cache_info = performance.get("cache", {})
        latency_info = performance.get("latency", {})
        accuracy_info = performance.get("accuracy", {})

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric("Total busquedas", f"{int(total_searches)}")
        with kpi2:
            st.metric("Cache hit ratio", f"{cache_info.get('hitRatio', summary.get('cacheHitRatio', 0)) * 100:.2f}%")
        with kpi3:
            st.metric("Latencia promedio", f"{latency_info.get('averageMs', summary.get('averageLatencyMs', 0)):.2f} ms")
        with kpi4:
            st.metric("Score promedio", f"{accuracy_info.get('averageScore', summary.get('averageScore', 0)):.4f}")

        st.markdown("---")
        st.subheader("Cache: Hits vs Misses")
        hits = cache_info.get("hits", summary.get("cacheHits", 0))
        misses = cache_info.get("misses", summary.get("cacheMisses", 0))
        col_cache_1, col_cache_2 = st.columns([2, 1])
        with col_cache_1:
            st.bar_chart(
                [
                    {"categoria": "Hits", "cantidad": hits},
                    {"categoria": "Misses", "cantidad": misses}
                ],
                x="categoria",
                y="cantidad",
                use_container_width=True
            )
        with col_cache_2:
            st.metric("Hits", int(hits))
            st.metric("Misses", int(misses))

        st.markdown("---")
        st.subheader("Latencia con cache vs sin cache")
        latency_with_cache = latency_info.get("withCacheMs", summary.get("averageLatencyWithCacheMs", 0))
        latency_without_cache = latency_info.get("withoutCacheMs", summary.get("averageLatencyWithoutCacheMs", 0))
        improvement = cache_info.get("improvement", 0)
        col_lat_1, col_lat_2 = st.columns([2, 1])
        with col_lat_1:
            st.bar_chart(
                [
                    {"tipo": "Con cache", "latenciaMs": latency_with_cache},
                    {"tipo": "Sin cache", "latenciaMs": latency_without_cache}
                ],
                x="tipo",
                y="latenciaMs",
                use_container_width=True
            )
        with col_lat_2:
            st.metric("Con cache", f"{latency_with_cache:.2f} ms")
            st.metric("Sin cache", f"{latency_without_cache:.2f} ms")
            st.metric("Mejora cache", f"{improvement * 100:.2f}%")

        st.markdown("---")
        st.subheader("Distribucion de resultados")
        resultado_distribution = distribution.get("resultado", summary.get("resultadoDistribution", {}))
        if resultado_distribution:
            st.bar_chart(
                [
                    {"resultado": key, "cantidad": value}
                    for key, value in resultado_distribution.items()
                ],
                x="resultado",
                y="cantidad",
                use_container_width=True
            )
        else:
            st.info("Sin datos de distribucion")

        if recent:
            st.markdown("---")
            recent_sorted = sorted(recent, key=lambda x: x.get("timestamp", ""))
            st.subheader("Requests Guru/Search: con cache vs sin cache")
            cache_accumulated = 0
            no_cache_accumulated = 0
            cache_vs_no_cache_series = []

            for item in recent_sorted:
                if item.get("cacheHit", False):
                    cache_accumulated += 1
                else:
                    no_cache_accumulated += 1

                cache_vs_no_cache_series.append(
                    {
                        "timestamp": item.get("timestamp"),
                        "Con cache": cache_accumulated,
                        "Sin cache": no_cache_accumulated
                    }
                )

            st.line_chart(
                cache_vs_no_cache_series,
                x="timestamp",
                y=["Con cache", "Sin cache"],
                use_container_width=True
            )

            st.markdown("---")
            st.subheader("Tendencia reciente de latencia (con/sin cache)")
            latency_by_cache_series = []
            cache_latency_sum = 0.0
            cache_latency_count = 0
            no_cache_latency_sum = 0.0
            no_cache_latency_count = 0

            for item in recent_sorted:
                cache_hit = item.get("cacheHit", False)
                latency_value = float(item.get("totalLatencyMs", 0) or 0)

                if cache_hit:
                    cache_latency_sum += latency_value
                    cache_latency_count += 1
                else:
                    no_cache_latency_sum += latency_value
                    no_cache_latency_count += 1

                avg_cache_latency = cache_latency_sum / cache_latency_count if cache_latency_count > 0 else 0
                avg_no_cache_latency = no_cache_latency_sum / no_cache_latency_count if no_cache_latency_count > 0 else 0

                latency_by_cache_series.append(
                    {
                        "timestamp": item.get("timestamp"),
                        "Latencia con cache": avg_cache_latency,
                        "Latencia sin cache": avg_no_cache_latency
                    }
                )

            st.line_chart(
                latency_by_cache_series,
                x="timestamp",
                y=["Latencia con cache", "Latencia sin cache"],
                use_container_width=True
            )

            with st.expander("Ver ultimas metricas (tabla)"):
                st.dataframe(
                    [
                        {
                            "timestamp": item.get("timestamp"),
                            "query": item.get("originalQuery"),
                            "resultado": item.get("resultado"),
                            "cacheHit": item.get("cacheHit"),
                            "score": item.get("score"),
                            "latencyMs": item.get("totalLatencyMs")
                        }
                        for item in recent_sorted
                    ],
                    use_container_width=True
                )

with tab5:
    st.header("Testing")

    if "golden_report" not in st.session_state:
        st.session_state.golden_report = None
    if "snapshot_comparison" not in st.session_state:
        st.session_state.snapshot_comparison = None
    if "duplicate_report" not in st.session_state:
        st.session_state.duplicate_report = None
    if "search_topn_report" not in st.session_state:
        st.session_state.search_topn_report = None
    if "quality_eval_result" not in st.session_state:
        st.session_state.quality_eval_result = None
    if "quality_feedback_stats" not in st.session_state:
        st.session_state.quality_feedback_stats = None
    if "quality_recent_feedback" not in st.session_state:
        st.session_state.quality_recent_feedback = []
    if "quality_batch_report" not in st.session_state:
        st.session_state.quality_batch_report = None

    testing_tab1, testing_tab2, testing_tab3, testing_tab4, testing_tab5 = st.tabs([
        "📊 Golden Dataset Testing",
        "🔄 Comparar Snapshots",
        "🔍 Detectar Duplicados",
        "🎯 Search Top N",
        "🎯 Calidad & Feedback",
    ])

    with testing_tab1:
        st.subheader("Golden Dataset Testing")
        st.markdown("Ejecuta tests de regresión")

        col_1, col_2, col_3 = st.columns([1, 2, 1])
        with col_1:
            snapshots = load_snapshots_list()
            active_version = get_active_snapshot_version()
            versions = [s.get("version") for s in snapshots if s.get("version")]
            if versions:
                try:
                    default_idx = versions.index(active_version) if active_version in versions else 0
                except (ValueError, IndexError):
                    default_idx = 0
                test_version = st.selectbox(
                    "Versión",
                    versions,
                    index=default_idx,
                    key="golden_version",
                    format_func=lambda v: format_snapshot_option(v, active_version),
                    help="Versión/snapshot para los tests. El activo está preseleccionado."
                )
            else:
                st.warning("⚠️ No hay snapshots disponibles")
                test_version = None
        with col_2:
            dataset_path = st.text_input("Dataset path (opcional)", value="", key="golden_dataset_path")
        with col_3:
            st.write("")
            run_golden = st.button("Ejecutar", type="primary", key="btn_run_golden")

        if run_golden:
            params = {"version": test_version}
            if dataset_path.strip():
                params["datasetPath"] = dataset_path.strip()
            with st.spinner("Ejecutando Golden Dataset..."):
                response = api_request("POST", "/testing/run-golden-dataset", params=params)
            if response and response.status_code == 200:
                st.session_state.golden_report = response.json()
                st.success("Ejecución completada")
            elif response:
                render_error_response(response)

        report = st.session_state.get("golden_report")
        if report:
            total_tests = int(report.get("totalTests", 0))
            passed = int(report.get("passed", 0))
            failed = int(report.get("failed", 0))
            pass_rate = float(report.get("passRate", 0))

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Total", total_tests)
            with k2:
                st.metric("Passed", passed)
            with k3:
                st.metric("Failed", failed)
            with k4:
                st.metric("Pass Rate", f"{pass_rate * 100:.1f}%")

            k5, k6, k7 = st.columns(3)
            with k5:
                st.metric("Duración", f"{report.get('totalDurationMs', 0)} ms")
            with k6:
                st.metric("Score Promedio", f"{float(report.get('averageScore', 0)):.3f}")
            with k7:
                st.metric("Respuestas Inactivas", int(report.get("inactiveAnswersReturned", 0)))

            by_category = report.get("byCategory", {})
            if by_category:
                st.markdown("---")
                st.subheader("Resultados por categoría")
                category_rows = []
                for cat_name, cat_metrics in by_category.items():
                    category_rows.append(
                        {
                            "Categoría": cat_name,
                            "Passed": int(cat_metrics.get("passed", 0)),
                            "Failed": int(cat_metrics.get("failed", 0)),
                            "Pass Rate (%)": float(cat_metrics.get("passRate", 0)) * 100,
                            "Score Promedio": float(cat_metrics.get("averageScore", 0)),
                        }
                    )
                st.dataframe(category_rows, use_container_width=True)
                st.bar_chart(
                    [{"Categoría": r["Categoría"], "Passed": r["Passed"], "Failed": r["Failed"]} for r in category_rows],
                    x="Categoría",
                    y=["Passed", "Failed"],
                    use_container_width=True,
                )

            failures = report.get("failures", [])
            st.markdown("---")
            if failures:
                st.subheader(f"Failures ({len(failures)})")
                for failure in failures:
                    title = f"{failure.get('testId', 'N/A')} - {failure.get('query', '')[:80]}"
                    with st.expander(title):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write("**Query:**", failure.get("query"))
                            st.write("**Categoría:**", failure.get("category"))
                            st.write("**Expected Key:**", failure.get("expectedAnswerKey"))
                            st.write("**Actual Key:**", failure.get("actualAnswerKey") or "N/A")
                            st.write("**Actual Answer ID:**", failure.get("actualAnswerId") or "N/A")
                        with c2:
                            st.write("**Expected Score:**", f">= {failure.get('expectedMinScore')}")
                            st.write("**Actual Score:**", f"{float(failure.get('actualScore', 0)):.3f}")
                            st.write("**Duración:**", f"{failure.get('durationMs', 0)} ms")
                            st.write("**Activa:**", "Sí" if failure.get("isActiveAnswer") else "No")
                        st.error(failure.get("failureReason") or "Sin detalle")
            else:
                st.success("Todos los tests pasaron")

    with testing_tab2:
        st.subheader("Comparar Snapshots")
        st.markdown("Compara dos versiones (A vs B)")

        snapshots = load_snapshots_list()
        active_version = get_active_snapshot_version()
        versions = [s.get("version") for s in snapshots if s.get("version")]

        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            if versions:
                try:
                    default_idx_a = versions.index(active_version) if active_version in versions else 0
                except (ValueError, IndexError):
                    default_idx_a = 0
                snapshot_a = st.selectbox(
                    "Snapshot A (Baseline)",
                    versions,
                    index=default_idx_a,
                    key="snap_a",
                    format_func=lambda v: format_snapshot_option(v, active_version),
                    help="Versión baseline para comparación"
                )
            else:
                st.warning("⚠️ No hay snapshots disponibles")
                snapshot_a = None
        with c2:
            if versions:
                try:
                    default_idx_b = min(1, len(versions) - 1) if len(versions) > 1 else 0
                except (ValueError, IndexError):
                    default_idx_b = 0
                snapshot_b = st.selectbox(
                    "Snapshot B (Candidate)",
                    versions,
                    index=default_idx_b,
                    key="snap_b",
                    format_func=lambda v: format_snapshot_option(v, active_version),
                    help="Versión candidata para comparación"
                )
            else:
                snapshot_b = None
        with c3:
            compare_dataset_path = st.text_input("Dataset path (opcional)", value="", key="compare_dataset_path")

        if st.button("Comparar", type="primary", key="btn_compare_snapshots"):
            payload = {"snapshotA": snapshot_a, "snapshotB": snapshot_b}
            if compare_dataset_path.strip():
                payload["datasetPath"] = compare_dataset_path.strip()
            with st.spinner("Comparando snapshots..."):
                response = api_request("POST", "/testing/compare-snapshots", json=payload)
            if response and response.status_code == 200:
                st.session_state.snapshot_comparison = response.json()
                st.success("Comparación completada")
            elif response:
                render_error_response(response)

        comparison = st.session_state.get("snapshot_comparison")
        if comparison:
            recommendation = comparison.get("recommendation", "")
            recommendation_lc = recommendation.lower()
            if "do not" in recommendation_lc or "no deploy" in recommendation_lc:
                st.error(f"Recomendación: {recommendation}")
            elif "deploy" in recommendation_lc:
                st.success(f"Recomendación: {recommendation}")
            else:
                st.warning(f"Recomendación: {recommendation}")

            snap_a_data = comparison.get("snapshotA", {})
            snap_b_data = comparison.get("snapshotB", {})

            st.markdown("---")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**{snap_a_data.get('version', 'A')} (Baseline)**")
                st.metric("Pass Rate", f"{float(snap_a_data.get('passRate', 0)) * 100:.1f}%")
                st.metric("Score Promedio", f"{float(snap_a_data.get('averageScore', 0)):.3f}")
                st.metric("Passed", int(snap_a_data.get("passed", 0)))
                st.metric("Failed", int(snap_a_data.get("failed", 0)))
            with col_b:
                st.markdown(f"**{snap_b_data.get('version', 'B')} (Candidate)**")
                pass_rate_delta = (float(snap_b_data.get("passRate", 0)) - float(snap_a_data.get("passRate", 0))) * 100
                score_delta = float(snap_b_data.get("averageScore", 0)) - float(snap_a_data.get("averageScore", 0))
                st.metric("Pass Rate", f"{float(snap_b_data.get('passRate', 0)) * 100:.1f}%", delta=f"{pass_rate_delta:+.1f}%")
                st.metric("Score Promedio", f"{float(snap_b_data.get('averageScore', 0)):.3f}", delta=f"{score_delta:+.3f}")
                st.metric("Passed", int(snap_b_data.get("passed", 0)), delta=int(snap_b_data.get("passed", 0)) - int(snap_a_data.get("passed", 0)))
                st.metric("Failed", int(snap_b_data.get("failed", 0)), delta=int(snap_b_data.get("failed", 0)) - int(snap_a_data.get("failed", 0)), delta_color="inverse")

            improvements = int(comparison.get("improvements", 0))
            regressions = int(comparison.get("regressions", 0))
            unchanged = int(comparison.get("unchanged", 0))

            st.markdown("---")
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("Improvements", improvements)
            with s2:
                st.metric("Regressions", regressions)
            with s3:
                st.metric("Unchanged", unchanged)

            st.bar_chart(
                [
                    {"Tipo": "Improvements", "Cantidad": improvements},
                    {"Tipo": "Regressions", "Cantidad": regressions},
                    {"Tipo": "Unchanged", "Cantidad": unchanged},
                ],
                x="Tipo",
                y="Cantidad",
                use_container_width=True,
            )

            changes = comparison.get("changes", [])
            if changes:
                st.markdown("---")
                st.subheader("Cambios detallados")
                change_filter = st.selectbox(
                    "Filtrar por tipo",
                    ["Todos", "IMPROVED", "REGRESSION", "UNCHANGED"],
                    key="change_filter",
                )
                filtered_changes = changes
                if change_filter != "Todos":
                    filtered_changes = [c for c in changes if c.get("changeType") == change_filter]

                for change in filtered_changes:
                    change_type = change.get("changeType", "UNCHANGED")
                    icon = "🟢" if change_type == "IMPROVED" else "🔴" if change_type == "REGRESSION" else "🟡"
                    title = f"{icon} {change.get('testId', 'N/A')} - {change.get('query', '')[:80]}"
                    with st.expander(title):
                        left, right = st.columns(2)
                        with left:
                            st.write(f"**{snap_a_data.get('version', 'A')}:**")
                            st.write("Answer Key:", change.get("versionAAnswerKey") or "N/A")
                            st.write("Answer ID:", change.get("versionAAnswerId") or "N/A")
                            st.write("Score:", f"{float(change.get('versionAScore', 0)):.3f}")
                        with right:
                            st.write(f"**{snap_b_data.get('version', 'B')}:**")
                            st.write("Answer Key:", change.get("versionBAnswerKey") or "N/A")
                            st.write("Answer ID:", change.get("versionBAnswerId") or "N/A")
                            st.write("Score:", f"{float(change.get('versionBScore', 0)):.3f}")

                        reason = change.get("reason")
                        if reason:
                            if change_type == "IMPROVED":
                                st.success(reason)
                            elif change_type == "REGRESSION":
                                st.error(reason)
                            else:
                                st.info(reason)

    with testing_tab3:
        st.subheader("Detectar Duplicados")
        st.markdown("Busca respuestas similares para detectar posibles duplicados")

        with st.form("form_find_duplicates"):
            d1, d2 = st.columns(2)
            with d1:
                dup_threshold = st.slider(
                    "Similarity Threshold",
                    min_value=0.0,
                    max_value=1.00,
                    value=0.95,
                    step=0.01,
                )
            with d2:
                dup_limit = st.number_input(
                    "Límite",
                    min_value=10,
                    max_value=100000,
                    value=100,
                    step=10,
                )

            st.warning("Con límites altos puede tardar varios minutos.")
            run_duplicates = st.form_submit_button("Buscar duplicados", type="primary")

        if run_duplicates:
            with st.spinner(f"Analizando {dup_limit} respuestas..."):
                payload = {"similarityThreshold": float(dup_threshold), "limit": int(dup_limit)}
                response = api_request("POST", "/testing/find-duplicates", json=payload)
            if response and response.status_code == 200:
                st.session_state.duplicate_report = response.json()
                st.success("Análisis completado")
            elif response:
                render_error_response(response)

        dup_report = st.session_state.get("duplicate_report")
        if dup_report:
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                st.metric("Respuestas analizadas", int(dup_report.get("totalAnswersAnalyzed", 0)))
            with p2:
                st.metric("Comparaciones", f"{int(dup_report.get('totalComparisonsPerformed', 0)):,}")
            with p3:
                st.metric("Duplicados encontrados", int(dup_report.get("duplicatePairsFound", 0)))
            with p4:
                st.metric("Duración", f"{dup_report.get('processingTimeMs', 0)} ms")

            st.info(dup_report.get("summary", ""))

            pairs = dup_report.get("highSimilarityPairs", [])
            if pairs:
                st.markdown("---")
                rec_filter = st.selectbox(
                    "Filtrar por recomendación",
                    ["Todos", "MERGE", "REVIEW", "MONITOR"],
                    key="rec_filter",
                )
                filtered_pairs = pairs
                if rec_filter != "Todos":
                    filtered_pairs = [p for p in pairs if rec_filter in (p.get("recommendation", ""))]

                for idx, pair in enumerate(filtered_pairs):
                    similarity = float(pair.get("similarity", 0))
                    recommendation = pair.get("recommendation", "")

                    if "MERGE" in recommendation:
                        icon = "🔴"
                        action = "Acción sugerida: mergear y conservar la más usada."
                    elif "REVIEW" in recommendation:
                        icon = "🟡"
                        action = "Acción sugerida: revisar manualmente antes de decidir."
                    else:
                        icon = "🟢"
                        action = "Acción sugerida: monitorear por ahora."

                    with st.expander(f"{icon} Par {idx + 1} · Similitud {similarity:.3f} · {recommendation}"):
                        q1, q2 = st.columns(2)
                        with q1:
                            st.markdown("**Respuesta 1**")
                            st.write("ID:", pair.get("answerId1"))
                            st.write("Veces retornada:", int(pair.get("timesReturned1", 0)))
                            st.text_area("Texto 1", pair.get("text1", ""), height=150, key=f"text1_{idx}", disabled=True)
                        with q2:
                            st.markdown("**Respuesta 2**")
                            st.write("ID:", pair.get("answerId2"))
                            st.write("Veces retornada:", int(pair.get("timesReturned2", 0)))
                            st.text_area("Texto 2", pair.get("text2", ""), height=150, key=f"text2_{idx}", disabled=True)

                        if "MERGE" in recommendation:
                            st.error(recommendation)
                        elif "REVIEW" in recommendation:
                            st.warning(recommendation)
                        else:
                            st.info(recommendation)
                        st.write(action)
            else:
                st.success("No se encontraron duplicados con el threshold configurado")

    with testing_tab4:
        st.subheader("Search Top N")
        st.markdown("Ejecuta búsqueda Top N para analizar ranking de respuestas")

        snapshots = load_snapshots_list()
        active_version = get_active_snapshot_version()
        versions = [s.get("version") for s in snapshots if s.get("version")]
        if versions:
            try:
                default_idx = versions.index(active_version) if active_version in versions else 0
            except (ValueError, IndexError):
                default_idx = 0
            topn_version = st.selectbox(
                "Versión/Snapshot",
                versions,
                index=default_idx,
                key="search_topn_version_select",
                format_func=lambda v: format_snapshot_option(v, active_version),
                help="Versión/snapshot para la búsqueda. El activo está preseleccionado."
            )
        else:
            st.warning("⚠️ No hay snapshots disponibles")
            topn_version = None

        with st.form("form_search_topn"):
            s1, s2, s3 = st.columns([3, 1, 1])
            with s1:
                topn_query = st.text_input("Query", key="search_topn_query", placeholder="Como veo mi saldo?")
            with s2:
                topn_value = st.number_input("Top N", min_value=1, max_value=20, value=5, step=1, key="search_topn_value")
            with s3:
                st.write("")

            run_topn = st.form_submit_button("Buscar Top N", type="primary")

        if run_topn:
            if not (topn_query or "").strip():
                st.warning("Ingresá una query para ejecutar Search Top N")
            else:
                params = {
                    "query": topn_query.strip(),
                    "topN": int(topn_value),
                }
                if (topn_version or "").strip():
                    params["version"] = topn_version.strip()

                with st.spinner("Consultando Search Top N..."):
                    response = api_request("GET", "/guru/search/top", params=params)

                if response and response.status_code == 200:
                    st.session_state.search_topn_report = response.json()
                    st.success("Search Top N ejecutado")
                elif response:
                    render_error_response(response)

        topn_report = st.session_state.get("search_topn_report")
        if topn_report:
            results = topn_report.get("results", []) or []
            latency = int(topn_report.get("latencyMs", 0) or 0)
            cache_hit = bool(topn_report.get("cacheHit", False))

            avg_score = sum(float(r.get("score", 0) or 0) for r in results) / len(results) if results else 0
            max_score = max((float(r.get("score", 0) or 0) for r in results), default=0)
            min_score = min((float(r.get("score", 0) or 0) for r in results), default=0)

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Resultados", len(results))
            with m2:
                st.metric("Latencia", f"{latency} ms")
            with m3:
                st.metric("Score promedio", f"{avg_score:.3f}")
            with m4:
                st.metric("Cache", "Sí" if cache_hit else "No")

            d1, d2 = st.columns(2)
            with d1:
                st.metric("Score máximo", f"{max_score:.3f}")
            with d2:
                st.metric("Score mínimo", f"{min_score:.3f}")

            if results:
                st.dataframe(
                    [
                        {
                            "Rank": idx + 1,
                            "Score": float(item.get("score", 0) or 0),
                            "PreguntaId": item.get("preguntaId"),
                            "RespuestaId": item.get("respuestaId"),
                            "Version": item.get("version"),
                            "TextoPregunta": item.get("textoPregunta", "")[:120],
                            "TextoRespuesta": item.get("textoRespuesta", "")[:160],
                        }
                        for idx, item in enumerate(results)
                    ],
                    use_container_width=True,
                )
            else:
                st.info("No hubo resultados para esa query/topN")

    with testing_tab5:
        st.subheader("Calidad & Feedback")
        quality_tab1, quality_tab2, quality_tab3 = st.tabs([
            "🤖 LLM Evaluator",
            "📊 Estadísticas Feedback",
            "🔬 Batch Evaluation",
        ])

        with quality_tab1:
            st.markdown("Evalúa calidad de una respuesta con LLM-as-a-judge")

            quality_respuestas = load_respuestas_catalog()
            quality_respuesta_map = {
                f"{r.get('id')} [{r.get('answerKey') or 'Sin key'}] - {(r.get('texto') or '')[:80]}": r
                for r in quality_respuestas
                if r.get("id")
            }

            with st.form("form_quality_evaluate"):
                eval_query = st.text_input("Query")
                eval_answer_label = st.selectbox(
                    "Respuesta a evaluar",
                    [""] + list(quality_respuesta_map.keys()),
                    key="select_quality_answer",
                )

                eval_selected_answer = quality_respuesta_map.get(eval_answer_label)
                eval_answer = (eval_selected_answer or {}).get("texto", "")
                eval_answer_id = (eval_selected_answer or {}).get("id", "")

                st.text_area(
                    "Texto de la respuesta seleccionada",
                    value=eval_answer,
                    height=150,
                    disabled=True,
                )

                run_eval = st.form_submit_button("🤖 Evaluar", type="primary")

            if run_eval:
                if not (eval_query or "").strip():
                    st.warning("Debes completar Query")
                elif not eval_answer_id:
                    st.warning("Debes seleccionar una respuesta de la lista")
                else:
                    payload = {
                        "query": eval_query.strip(),
                        "answerText": eval_answer.strip(),
                        "answerId": eval_answer_id,
                    }
                    with st.spinner("Evaluando calidad..."):
                        response = api_request("POST", "/quality/evaluate", json=payload)
                    if response and response.status_code == 200:
                        st.session_state.quality_eval_result = response.json()
                    elif response:
                        render_error_response(response)

            eval_result = st.session_state.get("quality_eval_result")
            if eval_result:
                is_correct = bool(eval_result.get("isCorrect", False))
                confidence = float(eval_result.get("confidence", 0))
                if is_correct:
                    st.success(f"✅ Respuesta CORRECTA (Confianza: {confidence:.0%})")
                else:
                    st.error(f"❌ Respuesta INCORRECTA (Confianza: {confidence:.0%})")

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("Relevancia", eval_result.get("relevance", "-"))
                with c2:
                    st.metric("Completitud", eval_result.get("completeness", "-"))
                with c3:
                    st.metric("Costo", f"${float(eval_result.get('evaluationCost', 0)):.4f}")
                with c4:
                    st.metric("Duración", f"{int(eval_result.get('evaluationTimeMs', 0))} ms")

                st.info(eval_result.get("reason", "Sin razón"))
                if eval_result.get("suggestedImprovement"):
                    st.warning(f"Mejora sugerida: {eval_result.get('suggestedImprovement')}")

        with quality_tab2:
            st.markdown("Consulta métricas agregadas de feedback")
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
            with c1:
                stats_from = st.date_input("Desde", value=datetime.now().date(), key="feedback_stats_from")
            with c2:
                stats_to = st.date_input("Hasta", value=datetime.now().date(), key="feedback_stats_to")
            with c3:
                st.write("")
                load_stats = st.button("📊 Cargar Stats", key="btn_load_feedback_stats", type="primary")
            with c4:
                recent_limit = st.number_input("Últimos feedbacks", min_value=5, max_value=200, value=25, step=5)

            if load_stats:
                params = {
                    "from": datetime.combine(stats_from, time.min).isoformat(),
                    "to": datetime.combine(stats_to, time.max).isoformat(),
                }
                response = api_request("GET", "/quality/feedback/stats", params=params)
                if response and response.status_code == 200:
                    st.session_state.quality_feedback_stats = response.json()
                elif response:
                    render_error_response(response)

                recent_response = api_request("GET", "/quality/feedback/recent", params={"limit": int(recent_limit)})
                if recent_response and recent_response.status_code == 200:
                    st.session_state.quality_recent_feedback = recent_response.json() or []
                elif recent_response:
                    render_error_response(recent_response)

            stats = st.session_state.get("quality_feedback_stats")
            if stats:
                k1, k2, k3, k4 = st.columns(4)
                with k1:
                    st.metric("Total", int(stats.get("totalFeedbacks", 0)))
                with k2:
                    st.metric("👍 Positivos", int(stats.get("positiveFeedbacks", 0)))
                with k3:
                    st.metric("👎 Negativos", int(stats.get("negativeFeedbacks", 0)))
                with k4:
                    st.metric("Tasa positiva", f"{float(stats.get('positiveRate', 0)):.1%}")

            recent_feedback = st.session_state.get("quality_recent_feedback", []) or []
            if recent_feedback:
                st.markdown("---")
                st.markdown("**🧾 Feedback reciente (detalle usuario)**")

                feedback_respuestas = load_respuestas_catalog()
                feedback_respuesta_by_id = {
                    r.get("id"): r.get("texto", "")
                    for r in feedback_respuestas
                    if r.get("id")
                }

                for idx, fb in enumerate(recent_feedback):
                    feedback_type = (fb.get("feedbackType") or "").lower()
                    icon = "👍" if feedback_type == "positive" else "👎"
                    answer_key = fb.get("answerKey") or "Sin key"
                    title = f"{icon} {fb.get('answerId', 'N/A')} [{answer_key}]"

                    with st.expander(title):
                        c_left, c_right = st.columns(2)
                        with c_left:
                            st.write("**Pregunta del usuario:**", fb.get("originalQuery") or "N/A")
                            st.write("**Comentario:**", fb.get("comment") or "(sin comentario)")
                            answer_text = feedback_respuesta_by_id.get(fb.get("answerId"), "")
                            st.write("**Texto de la respuesta:**", answer_text or "N/A")
                        with c_right:
                            timestamp = fb.get("timestamp") or "N/A"
                            st.write("**Fecha:**", timestamp)
                            st.write("**Tipo:**", fb.get("feedbackType") or "N/A")
                            st.write("**Versión:**", fb.get("version") or "N/A")
                            st.write("**Score:**", fb.get("score") if fb.get("score") is not None else "N/A")

        with quality_tab3:
            st.markdown("Ejecuta evaluación automática batch")
            with st.form("form_quality_batch"):
                b1, b2 = st.columns(2)
                with b1:
                    batch_sample_size = st.number_input("Tamaño de muestra", min_value=1, max_value=1000, value=50, step=1)
                with b2:
                    only_without_feedback = st.checkbox("Solo sin feedback", value=False)
                run_batch = st.form_submit_button("🚀 Evaluar Batch", type="primary")

            if run_batch:
                payload = {
                    "sampleSize": int(batch_sample_size),
                    "onlyWithoutFeedback": bool(only_without_feedback),
                }
                with st.spinner("Ejecutando evaluación batch..."):
                    response = api_request("POST", "/quality/batch-evaluate", json=payload)
                if response and response.status_code == 200:
                    st.session_state.quality_batch_report = response.json()
                elif response:
                    render_error_response(response)

            batch_report = st.session_state.get("quality_batch_report")
            if batch_report:
                r1, r2, r3, r4 = st.columns(4)
                with r1:
                    st.metric("Evaluadas", int(batch_report.get("totalEvaluated", 0)))
                with r2:
                    st.metric("Correctas", int(batch_report.get("correctAnswers", 0)))
                with r3:
                    st.metric("Incorrectas", int(batch_report.get("incorrectAnswers", 0)))
                with r4:
                    st.metric("Quality", f"{float(batch_report.get('qualityScore', 0)):.1%}")

                r5, r6 = st.columns(2)
                with r5:
                    st.metric("Ambiguas", int(batch_report.get("ambiguous", 0)))
                with r6:
                    st.metric("Costo", f"${float(batch_report.get('totalCost', 0)):.4f}")

                recommendations = batch_report.get("recommendations", []) or []
                if recommendations:
                    st.markdown("**💡 Recomendaciones**")
                    for rec in recommendations:
                        st.info(rec)

                failures = batch_report.get("failures", []) or []
                if failures:
                    st.markdown("**❌ Respuestas Incorrectas**")
                    for idx, failure in enumerate(failures):
                        exp_title = f"#{idx + 1} - {failure.get('answerId', 'N/A')} (conf {float(failure.get('confidence', 0)):.0%})"
                        with st.expander(exp_title):
                            st.write("Query:", failure.get("query", ""))
                            st.write("Relevancia:", failure.get("relevance", "-"))
                            st.write("Completitud:", failure.get("completeness", "-"))
                            st.error(failure.get("reason", "Sin razón"))
                            if failure.get("suggestedImprovement"):
                                st.warning(f"Mejora sugerida: {failure.get('suggestedImprovement')}")

with st.sidebar:
    st.header("Configuracion")
    st.caption(f"API: {API_URL}")

    if "config_summary" not in st.session_state:
        st.session_state.config_summary = None

    if st.button("🔄 Cargar configuración", key="btn_load_config"):
        response = api_request("GET", "/configuration/summary")
        if response and response.status_code == 200:
            st.session_state.config_summary = response.json()
        elif response:
            render_error_response(response)

    config_summary = st.session_state.get("config_summary")
    current_config = (config_summary or {}).get("current", {}) or {}

    current_threshold = current_config.get("threshold", 0.80)
    current_modified_by = current_config.get("modifiedBy") or "N/A"
    current_modified_date = current_config.get("modifiedDate") or "N/A"
    current_reason = current_config.get("reason") or "-"

    st.markdown("---")
    st.markdown("**Threshold actual**")
    st.metric("Search Threshold", f"{float(current_threshold):.2f}")
    st.caption(f"Modificado por: {current_modified_by}")
    st.caption(f"Fecha: {current_modified_date}")
    st.caption(f"Motivo: {current_reason}")

    st.markdown("---")
    st.markdown("**Actualizar threshold**")
    with st.form("form_update_threshold"):
        new_threshold = st.slider(
            "Nuevo threshold",
            min_value=0.0,
            max_value=1.0,
            value=float(current_threshold),
            step=0.01,
        )
        modified_by = st.text_input("Modificado por", value="admin")
        reason = st.text_input("Motivo (opcional)", value="")

        submit_threshold = st.form_submit_button("Guardar")

    if submit_threshold:
        payload = {
            "threshold": float(new_threshold),
            "modifiedBy": (modified_by or "").strip(),
            "reason": (reason or "").strip() or None,
        }
        response = api_request("PUT", "/configuration/threshold", json=payload)
        if response and response.status_code == 200:
            st.success("Threshold actualizado")
            refresh_response = api_request("GET", "/configuration/summary")
            if refresh_response and refresh_response.status_code == 200:
                st.session_state.config_summary = refresh_response.json()
            st.rerun()
        elif response:
            render_error_response(response)

    recent_changes = (config_summary or {}).get("recentChanges", []) or []
    if recent_changes:
        with st.expander("Historial reciente"):
            st.dataframe(
                [
                    {
                        "Threshold": item.get("threshold"),
                        "Anterior": item.get("previousValue"),
                        "Modificado por": item.get("modifiedBy"),
                        "Fecha": item.get("modifiedDate"),
                        "Motivo": item.get("reason") or "-",
                    }
                    for item in recent_changes
                ],
                use_container_width=True,
            )