import streamlit as st
import requests
from datetime import datetime, time, timedelta
from urllib.parse import quote
import os
import pandas as pd
import json
import math
import streamlit.components.v1 as components

st.set_page_config(page_title="Galicia Guru", page_icon=":robot:", layout="wide")

LOCAL_API_URL = "https://localhost:44321/api"
CLOUD_API_URL_DEFAULT = "https://poc-guru-hdf0gvb2a2f4ehgf.eastus-01.azurewebsites.net/"


def is_streamlit_cloud() -> bool:
    # Streamlit Community Cloud sets this marker.
    return os.getenv("STREAMLIT_SHARING_MODE", "").lower() == "community"


if is_streamlit_cloud():
    RUNTIME_ENV = "Cloud"
    API_URL = st.secrets.get("api_url") or os.getenv("API_URL") or CLOUD_API_URL_DEFAULT
else:
    RUNTIME_ENV = "Local"
    API_URL = LOCAL_API_URL


import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def emit_browser_log(message, payload=None):
    print(message)
    queue = st.session_state.setdefault("browser_console_queue", [])
    queue.append({"message": message, "payload": payload})


def flush_browser_logs():
    queue = st.session_state.get("browser_console_queue", [])
    if not queue:
        return

    script = f"""
    <script>
    (function () {{
        const logs = {json.dumps(queue)};
        logs.forEach(function (item) {{
            if (item.payload === null || item.payload === undefined) {{
                console.log(item.message);
            }} else {{
                console.log(item.message, item.payload);
            }}
        }});
    }})();
    </script>
    """
    components.html(script, height=0, width=0)
    st.session_state.browser_console_queue = []


def api_request(method, path, **kwargs):
    try:
        request_log = f"[API REQUEST] {method.upper()} {API_URL}{path}"
        # Mirror backend requests to browser DevTools console (F12).
        emit_browser_log(request_log)
        response = requests.request(method, f"{API_URL}{path}", verify=False, timeout=1500000, **kwargs)

        response_log = f"[API RESPONSE] {method.upper()} {API_URL}{path}"
        response_preview = ""
        try:
            response_preview = (response.text or "")[:500]
        except Exception:
            response_preview = "<no-text-preview>"

        emit_browser_log(
            response_log,
            {
                "status": int(response.status_code),
                "ok": bool(response.ok),
                "contentType": response.headers.get("Content-Type", ""),
                "bodyPreview": response_preview,
            },
        )

        return response
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


def to_float(value, default=0.0):
    try:
        if value is None:
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def parse_iso_datetime(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except Exception:
        return None


def build_requests_per_minute(recent_items):
    bucket = {}
    for item in recent_items or []:
        ts = parse_iso_datetime(item.get("timestamp"))
        if not ts:
            continue
        minute_key = ts.replace(second=0, microsecond=0).isoformat()
        bucket[minute_key] = bucket.get(minute_key, 0) + 1

    return [
        {"minute": minute_key, "requests": qty}
        for minute_key, qty in sorted(bucket.items(), key=lambda kv: kv[0])
    ]


def post_with_fallback(paths, **kwargs):
    for path in paths:
        response = api_request("POST", path, **kwargs)
        if response is not None and response.status_code < 500:
            return response, path
    return None, None


def to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "si", "y"):
            return True
        if lowered in ("false", "0", "no", "n"):
            return False
    return default


def first_present(item, *keys, default=None):
    for key in keys:
        if key in item and item.get(key) is not None:
            return item.get(key)
    return default


def first_non_empty_text(item, *keys):
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_top_results(raw_results):
    normalized = []
    for idx, result in enumerate(raw_results or []):
        if not isinstance(result, dict):
            continue
        answer_id = first_present(result, "answerId", "answer_id", "respuestaId", default=None)
        answer_key = first_present(result, "answerKey", "answer_key", default=None)
        answer_text = first_present(result, "answerText", "answer_text", "textoRespuesta", "text", default="")
        normalized.append(
            {
                "rank": int(first_present(result, "rank", default=idx + 1) or (idx + 1)),
                "respuestaId": answer_id,
                "answerId": answer_id,
                "answerKey": answer_key,
                "textoRespuesta": answer_text or "",
                "answerText": answer_text or "",
                "score": to_float(first_present(result, "score", default=0.0), default=0.0),
            }
        )
    return normalized


def normalize_recent_item(item):
    if not isinstance(item, dict):
        return {}

    original_query = first_non_empty_text(item, "originalQuery", "original_query", "query", "queryText", "query_text")
    normalized = {
        "id": first_present(item, "id", default=None),
        "queryHistoryId": first_present(item, "queryHistoryId", "query_history_id", "id", default=None),
        "queryHash": first_non_empty_text(item, "queryHash", "query_hash"),
        "originalQuery": original_query,
        "query": original_query,
        "processedQuery": first_non_empty_text(item, "processedQuery", "processed_query"),
        "answerId": first_present(item, "answerId", "answer_id", default=None),
        "answerText": first_present(item, "answerText", "answer_text", default="") or "",
        "score": to_float(first_present(item, "score", "confidence", default=0.0), default=0.0),
        "confidence": to_float(first_present(item, "score", "confidence", default=0.0), default=0.0),
        "confidenceLevel": first_present(item, "confidenceLevel", "confidence_level", default=None),
        "topResults": normalize_top_results(first_present(item, "topResults", "top_results", default=[])),
        "hasUserFeedback": to_bool(first_present(item, "hasUserFeedback", "has_user_feedback", default=False)),
        "hasQAReview": to_bool(first_present(item, "hasQAReview", "has_qa_review", default=False)),
        "needsReview": to_bool(first_present(item, "needsReview", "needs_review", default=False)),
        "cacheHit": to_bool(first_present(item, "cacheHit", "cache_hit", default=False)),
        "totalLatencyMs": to_float(first_present(item, "totalLatencyMs", "total_latency_ms", default=0.0), default=0.0),
        "timestamp": first_present(item, "timestamp", "createdAt", "created_at", default=None),
        "version": first_present(item, "version", default=None),
        "resultado": first_present(item, "resultado", "result", default=None),
    }
    return normalized


def normalize_recent_payload(payload):
    items = payload
    if isinstance(payload, dict):
        items = (
            payload.get("items")
            or payload.get("results")
            or payload.get("recent")
            or payload.get("reviews")
            or payload.get("data")
            or []
        )

    if not isinstance(items, list):
        return []

    normalized_items = []
    for item in items:
        normalized = normalize_recent_item(item)
        if normalized:
            normalized_items.append(normalized)
    return normalized_items


def build_feedback_payload(
    query_history_id,
    query_hash,
    original_query,
    answer_id,
    score,
    feedback_type,
    version,
    comment=None,
):
    # Enviar queryHistoryId permite actualizar feedback de forma precisa (1 solo documento).
    return {
        "queryHistoryId": (query_history_id or "").strip() or None,
        "queryHash": query_hash or "",
        "originalQuery": original_query or "",
        "answerId": answer_id,
        "score": score,
        "feedbackType": feedback_type,
        "comment": comment,
        "version": version,
    }


def build_feedback_tracking_key(query_history_id=None, query_hash=None, original_query=None):
    if (query_history_id or "").strip():
        return f"qh:{(query_history_id or '').strip()}"
    if (query_hash or "").strip():
        return f"qhsh:{(query_hash or '').strip()}"
    return f"q:{(original_query or '').strip().lower()}"

st.title("Galicia Guru - Sistema de Conocimiento")
st.markdown("---")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Busqueda",
    "Base Conocimiento",
    "Documentos",
    "Metricas",
    "Testing",
    "Dashboard QA",
    "Regression DataSet",
])

with tab1:
    st.header("Busqueda Inteligente")
    query = st.text_input("Tu pregunta:", placeholder="Como veo mi saldo?")

    if "search_result" not in st.session_state:
        st.session_state.search_result = None
    if "feedback_sent_keys" not in st.session_state:
        st.session_state.feedback_sent_keys = []

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
                    st.write("**QueryHistoryId:**", data.get("queryHistoryId") or "N/A")
                with detail_col3:
                    st.write("**Query original:**", debug_data.get("originalQuery") or data.get("query") or "N/A")
                    st.write("**Cache Hit:**", debug_data.get("cacheHit") if debug_data.get("cacheHit") is not None else "N/A")

                if debug_data:
                    st.markdown("**Debug payload**")
                    st.json(debug_data)
            
            # ✅ BOTONES DE FEEDBACK
            st.markdown("---")
            st.markdown("**¿Esta respuesta fue útil?**")
            feedback_key = build_feedback_tracking_key(
                query_history_id=data.get("queryHistoryId") or debug_data.get("queryHistoryId"),
                query_hash=debug_data.get("queryHash", ""),
                original_query=debug_data.get("originalQuery") or data.get("query"),
            )
            already_sent_feedback = feedback_key in (st.session_state.get("feedback_sent_keys") or [])

            if already_sent_feedback:
                st.success("✅ Feedback enviado para esta búsqueda")

            col_feedback1, col_feedback2, col_feedback3 = st.columns([1, 1, 4])
    
            with col_feedback1:
                if (not already_sent_feedback) and st.button("👍 Útil", key="btn_positive_feedback"):
                    feedback_payload = build_feedback_payload(
                        query_history_id=data.get("queryHistoryId") or debug_data.get("queryHistoryId"),
                        query_hash=debug_data.get("queryHash", ""),
                        original_query=debug_data.get("originalQuery") or data.get("query"),
                        answer_id=data.get("answerId"),
                        score=data.get("score"),
                        feedback_type="positive",
                        version=data.get("version"),
                    )
                    feedback_response = api_request("POST", "/quality/feedback", json=feedback_payload)
                    if feedback_response and feedback_response.status_code in (200, 201):
                        sent_keys = st.session_state.get("feedback_sent_keys") or []
                        if feedback_key not in sent_keys:
                            sent_keys.append(feedback_key)
                        st.session_state.feedback_sent_keys = sent_keys
                        st.success("✅ Gracias por tu feedback!")
                        st.rerun()
                    elif feedback_response:
                        st.error("Error enviando feedback")
    
            with col_feedback2:
                if (not already_sent_feedback) and st.button("👎 No útil", key="btn_negative_feedback"):
                    st.session_state.show_feedback_form = True
       
            # Formulario de feedback negativo con comentario
            if st.session_state.get("show_feedback_form", False):
                with st.form("form_negative_feedback"):
                    feedback_comment = st.text_area("¿Qué estuvo mal?", placeholder="Opcional: ayúdanos a mejorar")
                    submit_negative = st.form_submit_button("Enviar feedback")
                    
                    if submit_negative:
                        feedback_payload = build_feedback_payload(
                            query_history_id=data.get("queryHistoryId") or debug_data.get("queryHistoryId"),
                            query_hash=debug_data.get("queryHash", ""),
                            original_query=debug_data.get("originalQuery") or data.get("query"),
                            answer_id=data.get("answerId"),
                            score=data.get("score"),
                            feedback_type="negative",
                            version=data.get("version"),
                            comment=feedback_comment or None,
                        )
                        feedback_response = api_request("POST", "/quality/feedback", json=feedback_payload)
                        if feedback_response and feedback_response.status_code in (200, 201):
                            sent_keys = st.session_state.get("feedback_sent_keys") or []
                            if feedback_key not in sent_keys:
                                sent_keys.append(feedback_key)
                            st.session_state.feedback_sent_keys = sent_keys
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
        if "pending_resolution_message" not in st.session_state:
            st.session_state.pending_resolution_message = None

        pending_resolution_message = st.session_state.get("pending_resolution_message")
        if pending_resolution_message:
            st.success(pending_resolution_message)
            st.session_state.pending_resolution_message = None

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

            selected_pending_item = pending_map.get(selected_pending, {}) if selected_pending else {}
            pending_generated_answer = first_present(
                selected_pending_item,
                "respuestaGenIA",
                "respuesta_gen_ia",
                "generatedAnswer",
                default="",
            ) or ""

            with st.form("form_resolve_pending"):
                pending_usuario = st.text_input("Usuario", value="admin")
                pending_estado = st.selectbox("Estado", ["respondida", "cancelada"])
                pending_respuesta_final = st.text_area(
                    "Respuesta final (si respondida)",
                    value=pending_generated_answer,
                )
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
                            resolved_payload = response.json() or {}
                            st.session_state.pending_questions = [
                                item
                                for item in st.session_state.get("pending_questions", [])
                                if item.get("id") != pending_id
                            ]
                            resolved_text = resolved_payload.get("message") or "Pendiente actualizado"
                            st.session_state.pending_resolution_message = resolved_text
                            st.session_state.select_pending_question = ""
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
            st.session_state.metrics_payload["recent"] = normalize_recent_payload(recent_resp.json() or [])
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
                    feedback_type = (fb.get("feedbackType") or fb.get("feedback_type") or "").lower()
                    icon = "👍" if feedback_type == "positive" else "👎"
                    answer_key = fb.get("answerKey") or fb.get("answer_key") or "Sin key"
                    title = f"{icon} {fb.get('answerId') or fb.get('answer_id') or 'N/A'} [{answer_key}]"

                    with st.expander(title):
                        c_left, c_right = st.columns(2)
                        with c_left:
                            st.write("**Pregunta del usuario:**", fb.get("originalQuery") or fb.get("original_query") or "N/A")
                            st.write("**Comentario:**", fb.get("comment") or "(sin comentario)")
                            answer_text = (
                                fb.get("answerText")
                                or fb.get("answer_text")
                                or feedback_respuesta_by_id.get(fb.get("answerId") or fb.get("answer_id"), "")
                            )
                            st.write("**Texto de la respuesta:**", answer_text or "N/A")
                        with c_right:
                            timestamp = fb.get("timestamp") or "N/A"
                            st.write("**Fecha:**", timestamp)
                            st.write("**Tipo:**", fb.get("feedbackType") or fb.get("feedback_type") or "N/A")
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

with tab6:
    st.header("Dashboard QA y Negocio")
    st.caption("Vista unificada para monitoreo operativo, calidad del modelo y QA manual.")

    if "ops_dashboard" not in st.session_state:
        st.session_state.ops_dashboard = {}
    if "quality_runs" not in st.session_state:
        st.session_state.quality_runs = []
    if "qa_candidates" not in st.session_state:
        st.session_state.qa_candidates = []

    dash_tab1, dash_tab2, dash_tab3 = st.tabs([
        "🟦 Métricas Operativas",
        "🟩 Calidad",
        "🧠 QA Manual",
    ])

    with dash_tab1:
        st.subheader("Métricas Operativas")

        d1, d2, d3 = st.columns([1, 1, 1])
        with d1:
            ops_from = st.date_input("Desde", value=datetime.now().date() - timedelta(days=7), key="ops_from")
        with d2:
            ops_to = st.date_input("Hasta", value=datetime.now().date(), key="ops_to")
        with d3:
            ops_recent_limit = st.number_input(
                "Muestra reciente",
                min_value=50,
                max_value=5000,
                value=500,
                step=50,
                key="ops_recent_limit",
            )

        if st.button("Actualizar dashboard operativo", type="primary", key="btn_ops_refresh"):
            from_dt = datetime.combine(ops_from, time.min).isoformat()
            to_dt = datetime.combine(ops_to, time.max).isoformat()
            params_range = {"from": from_dt, "to": to_dt}

            with st.spinner("Cargando métricas operativas..."):
                summary_resp = api_request("GET", "/Metrics/summary", params=params_range)
                perf_resp = api_request("GET", "/Metrics/performance", params=params_range)
                dist_resp = api_request("GET", "/Metrics/distribution", params=params_range)
                recent_resp = api_request("GET", "/Metrics/recent", params={"limit": int(ops_recent_limit)})

            if summary_resp and summary_resp.status_code == 200:
                st.session_state.ops_dashboard["summary"] = summary_resp.json()
            elif summary_resp:
                render_error_response(summary_resp)

            if perf_resp and perf_resp.status_code == 200:
                st.session_state.ops_dashboard["performance"] = perf_resp.json()
            elif perf_resp:
                render_error_response(perf_resp)

            if dist_resp and dist_resp.status_code == 200:
                st.session_state.ops_dashboard["distribution"] = dist_resp.json()
            elif dist_resp:
                render_error_response(dist_resp)

            if recent_resp and recent_resp.status_code == 200:
                recent_raw = recent_resp.json() or []
                recent_normalized = normalize_recent_payload(recent_raw)
                st.session_state.ops_dashboard["recent"] = recent_normalized
                if isinstance(recent_raw, list):
                    raw_count = len(recent_raw)
                elif isinstance(recent_raw, dict):
                    raw_items = (
                        recent_raw.get("items")
                        or recent_raw.get("results")
                        or recent_raw.get("recent")
                        or recent_raw.get("reviews")
                        or recent_raw.get("data")
                        or []
                    )
                    raw_count = len(raw_items) if isinstance(raw_items, list) else 0
                else:
                    raw_count = 0

                st.session_state.ops_dashboard["recent_debug"] = {
                    "rawCount": raw_count,
                    "normalizedCount": len(recent_normalized),
                    "firstTimestamp": recent_normalized[0].get("timestamp") if recent_normalized else None,
                    "firstLatencyMs": recent_normalized[0].get("totalLatencyMs") if recent_normalized else None,
                }
                emit_browser_log(
                    "[OPS METRICS] /Metrics/recent normalized",
                    {
                        "count": len(recent_normalized),
                        "sample": recent_normalized[:2],
                    },
                )
            elif recent_resp:
                emit_browser_log(
                    "[OPS METRICS] /Metrics/recent error",
                    {"status": recent_resp.status_code, "body": recent_resp.text[:500]},
                )
                render_error_response(recent_resp)

        ops_payload = st.session_state.get("ops_dashboard", {})
        ops_summary = ops_payload.get("summary", {})
        ops_performance = ops_payload.get("performance", {})
        ops_distribution = ops_payload.get("distribution", {})
        ops_recent = ops_payload.get("recent", []) or []
        ops_recent_debug = ops_payload.get("recent_debug", {}) or {}

        if not ops_summary and not ops_performance:
            st.info("Presiona 'Actualizar dashboard operativo' para cargar datos.")
        else:
            total_searches = int(ops_performance.get("totalSearches", ops_summary.get("totalSearches", 0)) or 0)
            cache_info = ops_performance.get("cache", {}) or {}
            latency_info = ops_performance.get("latency", {}) or {}
            hit_ratio = to_float(cache_info.get("hitRatio", ops_summary.get("cacheHitRatio", 0)))
            avg_latency = to_float(latency_info.get("averageMs", ops_summary.get("averageLatencyMs", 0)))

            rpm_series = build_requests_per_minute(ops_recent)
            peak_rpm = max((row.get("requests", 0) for row in rpm_series), default=0)

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Consultas totales", total_searches)
            with k2:
                st.metric("Latencia promedio", f"{avg_latency:.2f} ms")
            with k3:
                st.metric("Cache hit ratio", f"{hit_ratio * 100:.2f}%")
            with k4:
                st.metric("Peak requests/min", int(peak_rpm))

            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Requests por minuto**")
                if rpm_series:
                    st.line_chart(rpm_series, x="minute", y="requests", use_container_width=True)
                else:
                    st.info("Sin datos suficientes para requests por minuto.")

            with c2:
                st.markdown("**Latencia reciente**")
                latency_series = [
                    {
                        "timestamp": item.get("timestamp"),
                        "latencyMs": to_float(item.get("totalLatencyMs", 0)),
                    }
                    for item in sorted(ops_recent, key=lambda x: x.get("timestamp", ""))
                ]
                if latency_series:
                    st.line_chart(latency_series, x="timestamp", y="latencyMs", use_container_width=True)
                else:
                    st.info("Sin datos recientes para latencia.")

            if ops_recent_debug:
                st.caption(
                    "Debug /Metrics/recent -> "
                    f"raw: {ops_recent_debug.get('rawCount', 0)} | "
                    f"normalized: {ops_recent_debug.get('normalizedCount', 0)} | "
                    f"firstTimestamp: {ops_recent_debug.get('firstTimestamp') or 'N/A'} | "
                    f"firstLatencyMs: {ops_recent_debug.get('firstLatencyMs') if ops_recent_debug.get('firstLatencyMs') is not None else 'N/A'}"
                )

            st.markdown("---")
            st.markdown("**Latencia por componente**")
            component_rows = []
            component_metrics = latency_info.get("components", {}) or {}
            for name, value in component_metrics.items():
                component_rows.append({"Componente": name, "LatencyMs": to_float(value)})

            if not component_rows:
                component_rows = [
                    {"Componente": "withCache", "LatencyMs": to_float(latency_info.get("withCacheMs", 0))},
                    {"Componente": "withoutCache", "LatencyMs": to_float(latency_info.get("withoutCacheMs", 0))},
                ]

            st.bar_chart(component_rows, x="Componente", y="LatencyMs", use_container_width=True)

            st.markdown("---")
            st.markdown("**Distribución de resultados**")
            result_distribution = ops_distribution.get("resultado", ops_summary.get("resultadoDistribution", {}))
            if result_distribution:
                distribution_rows = [
                    {"Resultado": key, "Cantidad": to_float(val)} for key, val in result_distribution.items()
                ]
                st.bar_chart(
                    distribution_rows,
                    x="Resultado",
                    y="Cantidad",
                    use_container_width=True,
                )
            else:
                st.info("Sin datos de distribución.")

    with dash_tab2:
        st.subheader("Calidad del Modelo")

        snapshots = load_snapshots_list()
        snapshot_versions = [s.get("version") for s in snapshots if s.get("version")]
        active_snapshot_version = get_active_snapshot_version()

        q1, q2,  q4 = st.columns([2, 2, 1])
        with q1:
            quality_dataset = st.selectbox(
                "Dataset",
                ["Golden", "Regresion"],
                key="quality_dataset_type",
            )
        with q2:
            if snapshot_versions:
                quality_snapshot = st.selectbox(
                    "Snapshot",
                    snapshot_versions,
                    index=snapshot_versions.index(active_snapshot_version) if active_snapshot_version in snapshot_versions else 0,
                    format_func=lambda v: format_snapshot_option(v, active_snapshot_version),
                    key="quality_snapshot",
                )
            else:
                st.warning("No hay snapshots.")
                quality_snapshot = None
        with q4:
            st.write("")
            run_quality = st.button("Ejecutar corrida", type="primary", key="btn_run_quality_dashboard")

        if run_quality:
            payload = {
                "useGoldenDataset": quality_dataset == "Golden",
                "version": quality_snapshot,
                "useFeedback": quality_dataset != "Golden",           
            }

            with st.spinner("Ejecutando métricas de calidad..."):
                ml_response, used_path = post_with_fallback([
                    "/mlmetrics/calculate",
                    "/mlmetrics/golden-dataset",
                ], json=payload, params={"version": quality_snapshot} if quality_snapshot else None)

            if ml_response and ml_response.status_code == 200:
                run_payload = ml_response.json() or {}
                run_payload["_sourcePath"] = used_path
                run_payload["_dataset"] = quality_dataset
                run_payload["_snapshot"] = quality_snapshot
                run_payload["_executedAt"] = datetime.now().isoformat()

                history = st.session_state.quality_runs
                history.append(run_payload)
                st.session_state.quality_runs = history[-25:]
                st.success("Corrida de calidad completada")
            elif ml_response:
                render_error_response(ml_response)
            else:
                st.error("No se pudo obtener respuesta de endpoints de ML metrics.")

        quality_runs = st.session_state.get("quality_runs", [])
        latest_run = quality_runs[-1] if quality_runs else None
        previous_run = quality_runs[-2] if len(quality_runs) > 1 else None

        if not latest_run:
            st.info("Ejecuta una corrida para ver métricas de calidad, deltas y matriz de confusión.")
        else:
            latest_accuracy = to_float(latest_run.get("accuracy", latest_run.get("passRate", 0)))
            latest_precision = to_float(latest_run.get("precision", 0))
            latest_recall = to_float(latest_run.get("recall", 0))
            latest_topk = to_float(
                latest_run.get("topKAccuracy", latest_run.get("topkAccuracy", latest_run.get("topK", 0)))
            )

            if previous_run:
                delta_accuracy = latest_accuracy - to_float(previous_run.get("accuracy", previous_run.get("passRate", 0)))
                delta_precision = latest_precision - to_float(previous_run.get("precision", 0))
                delta_recall = latest_recall - to_float(previous_run.get("recall", 0))
                delta_topk = latest_topk - to_float(
                    previous_run.get("topKAccuracy", previous_run.get("topkAccuracy", previous_run.get("topK", 0)))
                )
            else:
                delta_accuracy = delta_precision = delta_recall = delta_topk = 0.0

            st.caption(
                f"Última corrida: {latest_run.get('_executedAt', 'N/A')} | Dataset: {latest_run.get('_dataset', 'N/A')} | Snapshot: {latest_run.get('_snapshot', 'N/A')}"
            )

            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric(
                    "Accuracy",
                    f"{latest_accuracy * 100:.2f}%",
                    help="De todas las predicciones que hice, ¿qué porcentaje fue correcto? = (TP + TN) / (TP + FP + FN + TN)",
                )
            with m2:
                st.metric(
                    "Precision",
                    f"{latest_precision * 100:.2f}%",
                    help="De las respuestas que el sistema retornó, ¿cuántas eran correctas? = TP / (TP + FP)",
                )
            with m3:
                st.metric(
                    "Recall",
                    f"{latest_recall * 100:.2f}%",
                    help="De las respuestas correctas que existían, ¿cuántas encontró el sistema? = TP / (TP + FN)",
                )

            st.markdown("---")
            st.markdown("**Matriz de confusión**")

            cm = latest_run.get("confusionMatrix", {}) or {}
            tp = int(cm.get("truePositives", latest_run.get("truePositives", 0)) or 0)
            fp = int(cm.get("falsePositives", latest_run.get("falsePositives", 0)) or 0)
            fn = int(cm.get("falseNegatives", latest_run.get("falseNegatives", 0)) or 0)
            tn = int(cm.get("trueNegatives", latest_run.get("trueNegatives", 0)) or 0)

            cm_df = pd.DataFrame(
                [[tp, fn], [fp, tn]],
                index=["Real Positivo", "Real Negativo"],
                columns=["Pred Positivo", "Pred Negativo"],
            )
            st.dataframe(cm_df, use_container_width=True)

            st.markdown("---")
            st.markdown("**Support por respuesta/categoría**")
            support = latest_run.get("support", {}) or {}
            if support:
                support_rows = [{"item": key, "support": int(val)} for key, val in support.items()]
                st.dataframe(support_rows, use_container_width=True)
                st.bar_chart(support_rows, x="item", y="support", use_container_width=True)
            else:
                st.info("No hay información de support en la última corrida.")

            by_category = latest_run.get("byCategory", {}) or {}

            # Los datos de ejecución vienen dentro de detailedReport (MLMetrics/calculate)
            # o directamente en la raíz (testing/run-golden-dataset legacy).
            dr = latest_run.get("detailedReport") or {}
            has_golden_results = bool(dr) or any(
                key in latest_run
                for key in ["totalTests", "passed", "failed", "totalDurationMs", "averageScore", "failures"]
            )

            if has_golden_results:
                # Preferir detailedReport; caer a la raíz si no existe.
                gr = dr if dr else latest_run

                st.markdown("---")
                st.markdown("**Resultados de ejecución**")

                total_tests = int(gr.get("totalTests", 0) or 0)
                passed     = int(gr.get("passed", 0) or 0)
                failed     = int(gr.get("failed", 0) or 0)
                pass_rate  = to_float(gr.get("passRate", 0))

                g1, g2, g3, g4 = st.columns(4)
                with g1:
                    st.metric("Total", total_tests)
                with g2:
                    st.metric("Passed", passed)
                with g3:
                    st.metric("Failed", failed)
                with g4:
                    st.metric("Pass Rate", f"{pass_rate * 100:.1f}%")

                g5, g6, g7 = st.columns(3)
                with g5:
                    st.metric("Duración", f"{int(gr.get('totalDurationMs', 0) or 0)} ms")
                with g6:
                    st.metric("Score Promedio", f"{to_float(gr.get('averageScore', 0)):.3f}")
                with g7:
                    st.metric("Respuestas Inactivas", int(gr.get("inactiveAnswersReturned", 0) or 0))

                golden_by_cat = gr.get("byCategory", {}) or {}
                all_cats = sorted(set(list(by_category.keys()) + list(golden_by_cat.keys())))
                if all_cats:
                    unified_rows = []
                    for cat in all_cats:
                        root_d  = by_category.get(cat, {})
                        detail_d = golden_by_cat.get(cat, {})
                        unified_rows.append(
                            {
                                "Categoría": cat,
                                "Support": int(root_d.get("support", detail_d.get("totalTests", 0)) or 0),
                                "Passed": int(detail_d.get("passed", 0) or 0),
                                "Failed": int(detail_d.get("failed", 0) or 0),
                                "Accuracy": to_float(root_d.get("accuracy", root_d.get("passRate", 0))),
                                "Precision": to_float(root_d.get("precision", 0)),
                                "Recall": to_float(root_d.get("recall", 0)),
                                "Pass Rate (%)": to_float(detail_d.get("passRate", root_d.get("passRate", 0))) * 100,
                                "Score Promedio": to_float(detail_d.get("averageScore", root_d.get("averageScore", 0))),
                            }
                        )
                    st.markdown("---")
                    st.subheader("Por categoría")
                    st.dataframe(unified_rows, use_container_width=True)
                    chart_data = [{"Categoría": r["Categoría"], "Passed": r["Passed"], "Failed": r["Failed"]} for r in unified_rows if r["Passed"] > 0 or r["Failed"] > 0]
                    if chart_data:
                        st.bar_chart(
                            chart_data,
                            x="Categoría",
                            y=["Passed", "Failed"],
                            use_container_width=True,
                        )

                failures = gr.get("failures", []) or []
                st.markdown("---")
                if failures:
                    st.subheader(f"Failures ({len(failures)})")
                    for failure in failures:
                        title = f"{failure.get('testId', 'N/A')} - {str(failure.get('query', ''))[:80]}"
                        with st.expander(title):
                            f1, f2 = st.columns(2)
                            with f1:
                                st.write("**Query:**", failure.get("query"))
                                st.write("**Categoría:**", failure.get("category"))
                                st.write("**Expected Key:**", failure.get("expectedAnswerKey"))
                                st.write("**Actual Key:**", failure.get("actualAnswerKey") or "N/A")
                                st.write("**Actual Answer ID:**", failure.get("actualAnswerId") or "N/A")
                            with f2:
                                st.write("**Expected Score:**", f">= {failure.get('expectedMinScore')}")
                                st.write("**Actual Score:**", f"{to_float(failure.get('actualScore', 0)):.3f}")
                                st.write("**Duración:**", f"{int(failure.get('durationMs', 0) or 0)} ms")
                                st.write("**Activa:**", "Sí" if to_bool(failure.get("isActiveAnswer")) else "No")
                            st.error(failure.get("failureReason") or "Sin detalle")
                elif total_tests > 0:
                    st.success("Todos los tests pasaron")

    with dash_tab3:
        st.subheader("QA Manual")
        st.caption("Casos candidatos: preguntas ordenadas por menor confidence para revisión rápida.")

        qa_save_message = st.session_state.get("qa_save_message")
        if qa_save_message:
            st.success(qa_save_message)
            st.session_state.qa_save_message = None

        qa_col1, qa_col2, _ = st.columns([1, 1, 6])
        with qa_col1:
            qa_limit = st.number_input("Muestra base", min_value=10, max_value=100, value=20, step=10, key="qa_limit")
        with qa_col2:
            st.write("")
            st.write("")
            run_generate_qa = st.button("Generar lista QA", type="primary", key="btn_generate_qa")

        if run_generate_qa:
            with st.spinner(f"Armando lista automática de {qa_limit} preguntas..."):
                pending_response = api_request("GET", "/qa/pending-reviews", params={"limit": int(qa_limit)})

                candidates = []
                if pending_response and pending_response.status_code == 200:
                    pending_payload = pending_response.json() or {}
                    pending_reviews = (
                        pending_payload.get("reviews")
                        if isinstance(pending_payload, dict)
                        else pending_payload
                    ) or []

                    for review in pending_reviews:
                        normalized_review = normalize_recent_item(review)
                        top3 = normalize_top_results(
                            review.get("topResults")
                            or review.get("top_results")
                            or review.get("top3Alternatives")
                            or []
                        )
                        predicted = top3[0] if top3 else {
                            "answerId": normalized_review.get("answerId"),
                            "answerText": normalized_review.get("answerText") or "",
                        }

                        candidates.append(
                            {
                                "query": normalized_review.get("originalQuery") or normalized_review.get("query") or "",
                                "queryHistoryId": normalized_review.get("queryHistoryId") or review.get("queryHistoryId"),
                                "queryHash": normalized_review.get("queryHash") or review.get("queryHash", ""),
                                "version": normalized_review.get("version") or review.get("version"),
                                "timestamp": normalized_review.get("timestamp") or review.get("timestamp"),
                                "confidence": to_float(
                                    normalized_review.get("score", review.get("predictedScore", 0)),
                                    default=0.0,
                                ),
                                "predictedAnswerId": (
                                    predicted.get("respuestaId")
                                    or predicted.get("answerId")
                                    or normalized_review.get("answerId")
                                ),
                                "predictedAnswerText": (
                                    predicted.get("textoRespuesta")
                                    or predicted.get("answerText")
                                    or normalized_review.get("answerText")
                                    or ""
                                ),
                                "top3": top3,
                            }
                        )

                if not candidates:
                    st.info("No hay pendientes para QA manual en /qa/pending-reviews.")

                st.session_state.qa_candidates = candidates

        qa_candidates = st.session_state.get("qa_candidates", []) or []

        if not qa_candidates:
            st.info("Genera la lista QA para comenzar revisión manual.")
        else:
            st.success(f"{len(qa_candidates)} preguntas cargadas para QA manual")

            respuestas_catalog = load_respuestas_catalog()
            correct_options = {
                f"{r.get('id')} [{r.get('answerKey') or 'Sin key'}]": r
                for r in respuestas_catalog
                if r.get("id")
            }

            for global_idx, candidate in enumerate(qa_candidates):
                title = f"#{global_idx + 1} | conf {candidate.get('confidence', 0):.3f} | {candidate.get('query', '')[:90]}"

                with st.expander(title, expanded=(global_idx == 0)):
                    st.write("**Pregunta:**", candidate.get("query") or "N/A")
                    st.write("**Respuesta predicha:**", candidate.get("predictedAnswerText") or "N/A")
                    st.write("**AnswerId predicho:**", candidate.get("predictedAnswerId") or "N/A")
                    st.write("**Confidence:**", f"{to_float(candidate.get('confidence', 0)):.3f}")

                    top3 = candidate.get("top3", []) or []
                    if top3:
                        st.markdown("**Top 3 respuestas sugeridas**")
                        st.dataframe(
                            [
                                {
                                    "Rank": row.get("rank"),
                                    "RespuestaId": row.get("respuestaId"),
                                    "Score": row.get("score"),
                                    "Texto": (row.get("textoRespuesta") or "")[:200],
                                }
                                for row in top3
                            ],
                            use_container_width=True,
                        )

                    qa_decision = st.radio(
                        "Evaluación QA",
                        ["correcto", "incorrecto"],
                        horizontal=True,
                        key=f"qa_decision_{global_idx}",
                    )

                    selected_correct = ""
                    if qa_decision == "incorrecto":
                        selected_correct = st.selectbox(
                            "Seleccionar respuesta correcta",
                            [""] + list(correct_options.keys()),
                            key=f"qa_correct_{global_idx}",
                        )

                    qa_comment = st.text_area(
                        "Comentario QA (opcional)",
                        key=f"qa_comment_{global_idx}",
                        placeholder="Contexto para negocio/QA (error observado, detalle, etc.)",
                    )

                    if st.button("Guardar revisión", key=f"qa_save_{global_idx}"):
                        if qa_decision == "incorrecto" and not selected_correct:
                            st.warning("Selecciona la respuesta correcta antes de guardar.")
                        else:
                            feedback_type = "positive" if qa_decision == "correcto" else "negative"
                            correct_answer = correct_options.get(selected_correct, {}) if selected_correct else {}
                            qa_submit_ok = False
                            review_saved = False

                            comment_parts = []
                            if qa_comment.strip():
                                comment_parts.append(qa_comment.strip())
                            if qa_decision == "incorrecto":
                                comment_parts.append(
                                    f"QA_CORRECT_ANSWER_ID={correct_answer.get('id')} QA_CORRECT_ANSWER_KEY={correct_answer.get('answerKey')}"
                                )

                            if candidate.get("queryHistoryId"):
                                qa_payload = {
                                    "queryHistoryId": candidate.get("queryHistoryId"),
                                    "isCorrect": qa_decision == "correcto",
                                    "correctAnswerId": (
                                        None if qa_decision == "correcto" else correct_answer.get("id")
                                    ),
                                    "notes": " | ".join(comment_parts) if comment_parts else None,
                                    "reviewedBy": "streamlit-qa",
                                    "addToRegressionDataset": True,
                                }
                                qa_response = api_request("POST", "/qa/submit-review", json=qa_payload)
                                if qa_response and qa_response.status_code in (200, 201):
                                    qa_submit_ok = True
                                    review_saved = True
                                    st.success("Review QA guardada")
                                elif qa_response and qa_response.status_code != 404:
                                    render_error_response(qa_response)

                            if not qa_submit_ok:
                                feedback_payload = build_feedback_payload(
                                    query_history_id=candidate.get("queryHistoryId"),
                                    query_hash=candidate.get("queryHash") or "",
                                    original_query=candidate.get("query") or "",
                                    answer_id=candidate.get("predictedAnswerId"),
                                    score=candidate.get("confidence"),
                                    feedback_type=feedback_type,
                                    version=candidate.get("version"),
                                    comment=" | ".join(comment_parts) if comment_parts else None,
                                )

                                feedback_response = api_request("POST", "/quality/feedback", json=feedback_payload)
                                if feedback_response and feedback_response.status_code in (200, 201):
                                    review_saved = True
                                    st.success("Feedback QA guardado")
                                elif feedback_response:
                                    render_error_response(feedback_response)

                            if review_saved:
                                updated_candidates = st.session_state.get("qa_candidates", []) or []
                                if 0 <= global_idx < len(updated_candidates):
                                    updated_candidates.pop(global_idx)
                                    st.session_state.qa_candidates = updated_candidates
                                st.session_state.qa_save_message = "✅ Revisión guardada correctamente."
                                st.rerun()

                            st.caption("Regresión: gestionada automáticamente por el backend.")

with tab7:
    st.header("Regression DataSet")
    st.caption("Listado y desactivación de entradas. Alta y edición no disponibles por ahora.")

    if "regression_entries_payload" not in st.session_state:
        st.session_state.regression_entries_payload = {"total": 0, "entries": []}

    if st.button("Cargar Regression DataSet", type="primary", key="btn_load_regression_entries"):
        response = api_request("GET", "/Regression/entries")
        if response and response.status_code == 200:
            payload = response.json() or {}
            entries = payload.get("entries") if isinstance(payload, dict) else payload
            entries = entries or []
            total = payload.get("total", len(entries)) if isinstance(payload, dict) else len(entries)
            st.session_state.regression_entries_payload = {
                "total": int(total),
                "entries": entries,
            }
            st.success("Regression DataSet cargado")
        elif response:
            render_error_response(response)

    regression_payload = st.session_state.get("regression_entries_payload", {}) or {}
    regression_entries = regression_payload.get("entries", []) or []
    regression_total = int(regression_payload.get("total", len(regression_entries)) or 0)

    if not regression_entries:
        st.info("No hay registros cargados. Presiona 'Cargar Regression DataSet'.")
    else:
        st.metric("Total", regression_total)

        st.markdown("---")
        h1, h2, h3 = st.columns([4, 6, 2])
        with h1:
            st.markdown("**queryText**")
        with h2:
            st.markdown("**expectedAnswerText**")
        with h3:
            st.markdown("**Acción**")

        for idx, entry in enumerate(regression_entries):
            entry_id = entry.get("id")
            query_text = entry.get("queryText") or "-"
            expected_answer_text = entry.get("expectedAnswerText") or "-"

            c1, c2, c3 = st.columns([4, 6, 2])
            with c1:
                st.write(query_text)
            with c2:
                st.write(expected_answer_text)
            with c3:
                disable_btn = st.button(
                    "Deshabilitar",
                    key=f"btn_disable_reg_entry_{idx}",
                )

            if disable_btn and entry_id:
                encoded_entry_id = quote(str(entry_id), safe="")
                disable_response = api_request("DELETE", f"/Regression/entries/{encoded_entry_id}")
                if disable_response and disable_response.status_code in (200, 204):
                    st.success("Entrada desactivada")
                    updated_entries = st.session_state.regression_entries_payload.get("entries", []) or []
                    st.session_state.regression_entries_payload["entries"] = [
                        item
                        for item in updated_entries
                        if item.get("id") != entry_id
                    ]
                    st.rerun()
                elif disable_response:
                    render_error_response(disable_response)

with st.sidebar:
    st.header("Configuracion")
    st.caption(f"Entorno: {RUNTIME_ENV}")
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

flush_browser_logs()