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
    # Streamlit Cloud markers can vary by runtime; support common alternatives.
    sharing_mode = os.getenv("STREAMLIT_SHARING_MODE", "").strip().lower()
    if sharing_mode in ("community", "cloud"):
        return True

    cloud_markers = [
        os.getenv("IS_STREAMLIT_CLOUD", ""),
        os.getenv("STREAMLIT_RUNTIME", ""),
        os.getenv("STREAMLIT_ENV", ""),
    ]
    return any(str(marker).strip().lower() in ("1", "true", "yes", "cloud") for marker in cloud_markers)


configured_api_url = os.getenv("API_URL") or st.secrets.get("api_url")

if configured_api_url:
    API_URL = configured_api_url
    RUNTIME_ENV = "Cloud" if is_streamlit_cloud() else "Configured"
elif is_streamlit_cloud():
    RUNTIME_ENV = "Cloud"
    API_URL = CLOUD_API_URL_DEFAULT
else:
    # Default a CLOUD_API_URL si no hay config y no está en cloud detectado
    # (fallback seguro para Streamlit Cloud que no detecta correctamente)
    RUNTIME_ENV = "Local"
    API_URL = CLOUD_API_URL_DEFAULT  # Cambié de LOCAL_API_URL a CLOUD_API_URL_DEFAULT


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


def build_requests_per_hour(recent_items):
    bucket = {}
    for item in recent_items or []:
        ts = parse_iso_datetime(item.get("timestamp"))
        if not ts:
            continue
        hour_key = ts.replace(minute=0, second=0, microsecond=0).isoformat()
        bucket[hour_key] = bucket.get(hour_key, 0) + 1

    return [
        {"hour": hour_key, "requests": qty}
        for hour_key, qty in sorted(bucket.items(), key=lambda kv: kv[0])
    ]


def build_cache_accumulated_by_day(recent_items):
    bucket = {}
    for item in recent_items or []:
        ts = parse_iso_datetime(item.get("timestamp"))
        if not ts:
            continue
        day_key = ts.date().isoformat()
        day_bucket = bucket.setdefault(day_key, {"cache": 0, "no_cache": 0})
        if item.get("cacheHit", False):
            day_bucket["cache"] += 1
        else:
            day_bucket["no_cache"] += 1

    cache_accumulated = 0
    no_cache_accumulated = 0
    series = []
    for day_key in sorted(bucket.keys()):
        cache_accumulated += bucket[day_key]["cache"]
        no_cache_accumulated += bucket[day_key]["no_cache"]
        series.append(
            {
                "day": day_key,
                "Con cache": cache_accumulated,
                "Sin cache": no_cache_accumulated,
            }
        )

    return series


def build_latency_average_by_day(recent_items):
    bucket = {}
    for item in recent_items or []:
        ts = parse_iso_datetime(item.get("timestamp"))
        if not ts:
            continue
        day_key = ts.date().isoformat()
        day_bucket = bucket.setdefault(
            day_key,
            {
                "cache_sum": 0.0,
                "cache_count": 0,
                "no_cache_sum": 0.0,
                "no_cache_count": 0,
            },
        )
        latency_value = float(item.get("totalLatencyMs", 0) or 0)

        if item.get("cacheHit", False):
            day_bucket["cache_sum"] += latency_value
            day_bucket["cache_count"] += 1
        else:
            day_bucket["no_cache_sum"] += latency_value
            day_bucket["no_cache_count"] += 1

    series = []
    for day_key in sorted(bucket.keys()):
        day_bucket = bucket[day_key]
        avg_cache = day_bucket["cache_sum"] / day_bucket["cache_count"] if day_bucket["cache_count"] > 0 else 0
        avg_no_cache = day_bucket["no_cache_sum"] / day_bucket["no_cache_count"] if day_bucket["no_cache_count"] > 0 else 0
        series.append(
            {
                "day": day_key,
                "Latencia con cache": avg_cache,
                "Latencia sin cache": avg_no_cache,
            }
        )

    return series


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

tab1, tab2, tab3, tab4 = st.tabs([
    "🔎 Busqueda",
    "📚 Base Conocimiento",
    "📊 Dashboard",
    "🧪 QA & Mejora Continua",
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
            score_obtenido = data.get("score")
            if score_obtenido is None:
                score_obtenido = debug_data.get("score")
            if score_obtenido is None:
                score_obtenido = debug_data.get("confidence")
            st.success(data['answer'])
            
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
            with st.expander("Ver detalle del resultado"):
                detail_col1, detail_col2, detail_col3 = st.columns(3)
                with detail_col1:
                    st.write("**Answer ID:**", data.get("answerId") or "N/A")
                    st.write("**Version:**", data.get("version") or "N/A")
                    st.write("**Threshold:**", data.get("threshold") if data.get("threshold") is not None else "N/A")
                with detail_col2:
                    st.write("**Score obtenido:**", score_obtenido if score_obtenido is not None else "N/A")
                    st.write("**Latency (ms):**", data.get("latencyMs") if data.get("latencyMs") is not None else "N/A")
                    st.write("**Cache Hit:**", "Sí" if data.get("cacheHit") else "No")
                with detail_col3:
                    st.write("**Query Hash:**", debug_data.get("queryHash") or "N/A")
                    st.write("**QueryHistoryId:**", data.get("queryHistoryId") or "N/A")
                    st.write("**Idioma detectado:**", debug_data.get("detectedLanguage") or "N/A")

                st.markdown("---")
                st.markdown("**Query**")
                st.write("**Original:**", debug_data.get("originalQuery") or data.get("query") or "N/A")
                st.write("**Procesada:**", debug_data.get("processedQuery") or "N/A")
                st.write("**Modificada:**", "Sí" if debug_data.get("wasModified") else "No")

                if debug_data:
                    st.markdown("---")
                    st.markdown("**Debug completo**")
                    st.json(debug_data)
        elif result["type"] == "no_answer":
            st.warning(result["msg"])
            st.info("La pregunta se guardó para revisión")
        elif result["type"] == "error":
            st.error(f"Error {result['code']}: {result['text']}")

with tab2:
    st.header("Base de Conocimiento")

    kb_tab1, kb_tab2, kb_tab3, kb_tab4 = st.tabs(["💡 Respuestas", "📄 Documentos", "❓ Preguntas", "📸 Snapshots"])

    with kb_tab1:
        st.subheader("💡 Respuestas")

        if "respuestas" not in st.session_state:
            st.session_state.respuestas = []
        if "kb_respuesta_edit_message" not in st.session_state:
            st.session_state.kb_respuesta_edit_message = None
        if "respuestas_auto_loaded" not in st.session_state:
            st.session_state.respuestas_auto_loaded = False

        kb_respuesta_edit_message = st.session_state.get("kb_respuesta_edit_message")
        if kb_respuesta_edit_message:
            st.success(kb_respuesta_edit_message)
            st.session_state.kb_respuesta_edit_message = None

        # Auto-load respuestas on first entry
        if not st.session_state.respuestas_auto_loaded:
            response = api_request("GET", "/kb/respuestas")
            if response and response.status_code == 200:
                st.session_state.respuestas = response.json()
                st.session_state.respuestas_catalog = response.json()
                st.session_state.respuestas_auto_loaded = True
            elif response:
                render_error_response(response)

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
                    "answerKey": (new_respuesta_answer_key or "").upper() or None,
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
        if st.session_state.pop("clear_edit_respuesta_next_run", False):
            st.session_state["select_edit_respuesta"] = ""
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
                        refreshed_respuestas = api_request("GET", "/kb/respuestas")
                        if refreshed_respuestas and refreshed_respuestas.status_code == 200:
                            refreshed_payload = refreshed_respuestas.json() or []
                            st.session_state.respuestas = refreshed_payload
                            st.session_state.respuestas_catalog = refreshed_payload
                            if result.get("message") == "Nueva version creada":
                                st.session_state.kb_respuesta_edit_message = f"Nueva versión creada - ID: {result.get('nuevaRespuestaId')}"
                            else:
                                st.session_state.kb_respuesta_edit_message = "Respuesta actualizada"
                            st.session_state["clear_edit_respuesta_next_run"] = True
                            st.rerun()
                        elif refreshed_respuestas:
                            render_error_response(refreshed_respuestas)
                            st.error("La respuesta se actualizó, pero falló la recarga del listado.")
                        else:
                            st.error("La respuesta se actualizó, pero no se pudo refrescar la lista.")
                    elif response:
                        render_error_response(response)
                    else:
                        st.error("No se pudo actualizar la respuesta (sin respuesta del backend).")

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

    with kb_tab2:
        st.subheader("📄 Documentos")
        
        if "documentos" not in st.session_state:
            st.session_state.documentos = []
        if "documentos_auto_loaded" not in st.session_state:
            st.session_state.documentos_auto_loaded = False

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
                    st.session_state.documentos_auto_loaded = False
                elif response:
                    render_error_response(response)

        # Auto-load documentos on first entry
        if not st.session_state.documentos_auto_loaded:
            response = api_request("GET", "/documents")
            if response and response.status_code == 200:
                st.session_state.documentos = response.json()
                st.session_state.documentos_auto_loaded = True
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
                doc_is_active = to_bool(
                    first_present(doc, "isActive", "activo", "active", default=True),
                    default=True,
                )

                col1, col2 = st.columns([4, 1])
                with col1:
                    status = "Activo" if doc_is_active else "Inactivo"
                    st.write(f"{doc['fileName']} ({doc['totalChunks']} chunks) - {status}")
                with col2:
                    action_label = "Desactivar" if doc_is_active else "Activar"
                    action_path = "deactivate" if doc_is_active else "activate"
                    if st.button(action_label, key=f"toggle_doc_{doc['fileName']}"):
                        encoded_filename = quote(doc['fileName'], safe='')
                        toggle_resp = api_request("POST", f"/documents/{encoded_filename}/{action_path}")
                        if toggle_resp and toggle_resp.status_code == 200:
                            st.success(f"Documento {action_label.lower()}do")
                            refresh_docs_resp = api_request("GET", "/documents")
                            if refresh_docs_resp and refresh_docs_resp.status_code == 200:
                                st.session_state.documentos = refresh_docs_resp.json()
                            st.rerun()
                        elif toggle_resp:
                            render_error_response(toggle_resp)

    with kb_tab3:
        st.subheader("❓ Preguntas")

        if "preguntas" not in st.session_state:
            st.session_state.preguntas = []
        if "kb_pregunta_edit_message" not in st.session_state:
            st.session_state.kb_pregunta_edit_message = None
        if "preguntas_auto_loaded" not in st.session_state:
            st.session_state.preguntas_auto_loaded = False

        kb_pregunta_edit_message = st.session_state.get("kb_pregunta_edit_message")
        if kb_pregunta_edit_message:
            st.success(kb_pregunta_edit_message)
            st.session_state.kb_pregunta_edit_message = None

        # Auto-load preguntas on first entry
        if not st.session_state.preguntas_auto_loaded:
            response = api_request("GET", "/kb/preguntas")
            if response and response.status_code == 200:
                st.session_state.preguntas = response.json()
                st.session_state.preguntas_auto_loaded = True
            elif response:
                render_error_response(response)

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
                    (new_pregunta_answer_key or "").upper() or None,
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
        if st.session_state.pop("clear_edit_pregunta_next_run", False):
            st.session_state["select_edit_pregunta"] = ""
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
                            refreshed_preguntas = api_request("GET", "/kb/preguntas")
                            if refreshed_preguntas and refreshed_preguntas.status_code == 200:
                                st.session_state.preguntas = refreshed_preguntas.json() or []
                                st.session_state.kb_pregunta_edit_message = "Pregunta actualizada"
                                st.session_state["clear_edit_pregunta_next_run"] = True
                                st.rerun()
                            elif refreshed_preguntas:
                                render_error_response(refreshed_preguntas)
                                st.error("La pregunta se actualizó, pero falló la recarga del listado.")
                            else:
                                st.error("La pregunta se actualizó, pero no se pudo refrescar la lista.")
                        elif response:
                            render_error_response(response)
                        else:
                            st.error("No se pudo actualizar la pregunta (sin respuesta del backend).")

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

    with kb_tab4:
        st.subheader("📸 Snapshots")

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
            snapshot_threshold = st.slider(
                "Threshold",
                min_value=0.0,
                max_value=1.0,
                value=0.80,
                step=0.01,
                help="Threshold que se guardará de forma inmutable en la versión de snapshot"
            )
            create_snapshot = st.form_submit_button("Crear snapshot")

            if create_snapshot:
                payload = {
                    "version": snapshot_version,
                    "setAsActive": snapshot_set_active,
                    "threshold": float(snapshot_threshold),
                }

                with st.spinner("Creando snapshot..."):
                    response = api_request("POST", "/versioning/snapshots", json=payload)
                if response and response.status_code == 200:
                    st.success("Snapshot creado")
                    st.json(response.json())
                elif response:
                    render_error_response(response)

    if False:
        st.subheader("Preguntas sin responder")

        if "pending_questions" not in st.session_state:
            st.session_state.pending_questions = []
        if "pending_resolution_message" not in st.session_state:
            st.session_state.pending_resolution_message = None
        if "pending_questions_auto_loaded" not in st.session_state:
            st.session_state.pending_questions_auto_loaded = False

        pending_resolution_message = st.session_state.get("pending_resolution_message")
        if pending_resolution_message:
            st.success(pending_resolution_message)
            st.session_state.pending_resolution_message = None

        # Auto-load pending questions on first entry
        if not st.session_state.pending_questions_auto_loaded:
            response = api_request("GET", "/kb/unanswered-questions/pending", params={"limit": 20})
            if response and response.status_code == 200:
                st.session_state.pending_questions = response.json()
                st.session_state.pending_questions_auto_loaded = True
            elif response:
                render_error_response(response)

        if st.button("Ver pendientes", key="btn_pending_questions"):
            response = api_request("GET", "/kb/unanswered-questions/pending", params={"limit": 20})
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

            # Estado fuera del form para controlar qué campos se muestran
            pending_estado = st.selectbox("Estado", ["respondida", "cancelada"], key="pending_estado_select")

            # Cargar catálogo de respuestas solo si se va a usar
            pending_resolution_mode = st.session_state.get("pending_resolution_mode_radio", "Usar respuesta existente")
            respuestas_catalog_pending = []
            answer_options_pending = {}
            if pending_estado == "respondida":
                respuestas_catalog_pending = load_respuestas_catalog()
                answer_options_pending = {
                    f"{r.get('id')} [{r.get('answerKey') or 'Sin key'}] - {(r.get('texto') or '')[:60]}": r
                    for r in respuestas_catalog_pending
                    if r.get("id")
                }
                pending_resolution_mode = st.radio(
                    "Resolución en KB",
                    ["Usar respuesta existente", "Crear nueva respuesta"],
                    horizontal=True,
                    key="pending_resolution_mode_radio",
                )

            with st.form("form_resolve_pending"):
                pending_usuario = st.text_input("Usuario", value="admin")

                if pending_estado == "respondida":
                    pending_question_text = st.text_area(
                        "Texto de pregunta (opcional)",
                        value=first_present(selected_pending_item, "queryProcesada", "queryOriginal", "query", "question", "pregunta", default="") or "",
                        help="Si no se completa, se usa el texto original de la pregunta pendiente.",
                    )

                    selected_existing_answer_label = ""
                    selected_existing_answer_id = ""
                    new_pending_answer_text = ""
                    new_pending_answer_key = ""

                    if pending_resolution_mode == "Usar respuesta existente":
                        selected_existing_answer_label = st.selectbox(
                            "Respuesta existente",
                            [""] + list(answer_options_pending.keys()),
                        )
                        selected_existing_answer_id = (answer_options_pending.get(selected_existing_answer_label) or {}).get("id", "")
                    else:
                        new_pending_answer_text = st.text_area(
                            "Texto de nueva respuesta",
                            value=pending_generated_answer,
                            placeholder="Escribe la respuesta final para guardar en KB",
                        )
                        new_pending_answer_key = st.text_input(
                            "ANSWER_KEY (opcional)",
                            placeholder="EJ: SALDO_CONSULTA",
                            help="Si lo dejas vacío, el backend lo genera automáticamente.",
                        )
                else:
                    pending_question_text = ""
                    selected_existing_answer_id = ""
                    new_pending_answer_text = ""
                    new_pending_answer_key = ""

                pending_observaciones = st.text_area("Observaciones")
                submit_pending = st.form_submit_button("Guardar resolucion")

                if submit_pending:
                    if not selected_pending:
                        st.warning("Selecciona una pregunta pendiente")
                    elif pending_estado == "cancelada" and not pending_observaciones.strip():
                        st.warning("Completa las observaciones para cancelar")
                    elif pending_estado == "respondida" and pending_resolution_mode == "Usar respuesta existente" and not selected_existing_answer_id:
                        st.warning("Selecciona una respuesta existente")
                    elif pending_estado == "respondida" and pending_resolution_mode == "Crear nueva respuesta" and not new_pending_answer_text.strip():
                        st.warning("Completa el texto de la nueva respuesta")
                    else:
                        pending_id = pending_map[selected_pending].get("id")
                        payload = {
                            "estado": pending_estado,
                            "usuario": pending_usuario,
                            "preguntaTexto": (pending_question_text or "").strip() or None,
                            "respuestaIdExistente": (
                                selected_existing_answer_id
                                if pending_estado == "respondida" and pending_resolution_mode == "Usar respuesta existente"
                                else None
                            ),
                            "respuestaTextoNueva": (
                                new_pending_answer_text.strip()
                                if pending_estado == "respondida" and pending_resolution_mode == "Crear nueva respuesta"
                                else None
                            ),
                            "respuestaAnswerKey": (
                                new_pending_answer_key.strip()
                                if pending_estado == "respondida" and pending_resolution_mode == "Crear nueva respuesta"
                                else None
                            ),
                            "observaciones": pending_observaciones.strip() or None
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
                            st.session_state.pop("select_pending_question", None)
                        elif response:
                            render_error_response(response)
        else:
            st.info("No hay pendientes cargados. Usa 'Ver pendientes'.")

with tab4:
    st.header("QA & Mejora Continua")

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
    if "quality_batch_report" not in st.session_state:
        st.session_state.quality_batch_report = None

    testing_tab1, testing_tab2, testing_tab3, testing_tab4, testing_tab5 = st.tabs([
        "📋 Cola de revisión",
        "🧪 Regression DataSet",
        "🔍 Detectar Duplicados",
        "🎯 Search Top N",
        "🤖 LLM Evaluator",
    ])

    if False:
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

    if False:
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
                            "Score": f"{float(item.get('score', 0) or 0):.4f}",
                            "PreguntaId": item.get("preguntaId") or "-",
                            "RespuestaId": item.get("respuestaId", "")[:36],
                            "TextoPregunta": item.get("textoPregunta") or topn_query or "(vacío)",
                            "TextoRespuesta": item.get("textoRespuesta", "")[:100],
                        }
                        for idx, item in enumerate(results)
                    ],
                    use_container_width=True,
                )
            else:
                st.info("No hubo resultados para esa query/topN")

    with testing_tab5:
        st.subheader("LLM Evaluator")
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

    if False:
        st.subheader("Estadísticas Feedback")
        st.markdown("Consulta métricas agregadas de feedback")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            stats_from = st.date_input("Desde", value=datetime.now().date(), key="feedback_stats_from")
        with c2:
            stats_to = st.date_input("Hasta", value=datetime.now().date(), key="feedback_stats_to")
        with c3:
            st.write("")
            load_stats = st.button("📊 Cargar Stats", key="btn_load_feedback_stats", type="primary")

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

with tab3:
    st.header("Dashboard")
    st.caption("Vista unificada para monitoreo operativo y calidad del modelo.")

    if "ops_dashboard" not in st.session_state:
        st.session_state.ops_dashboard = {}
    if "quality_runs" not in st.session_state:
        st.session_state.quality_runs = []
    if "qa_candidates" not in st.session_state:
        st.session_state.qa_candidates = []

    dash_tab1, dash_tab2 = st.tabs([
        "🟦 Operativo",
        "🟩 Calidad",
    ])

    with dash_tab1:
        st.subheader("Métricas Operativas")

        d1, d2 = st.columns([1, 1])
        with d1:
            ops_from = st.date_input("Desde", value=datetime.now().date() - timedelta(days=7), key="ops_from")
        with d2:
            ops_to = st.date_input("Hasta", value=datetime.now().date(), key="ops_to")

        ops_recent_limit = 500

        if st.button("Actualizar dashboard operativo", type="primary", key="btn_ops_refresh"):
            from_dt = datetime.combine(ops_from, time.min).isoformat()
            to_dt = datetime.combine(ops_to, time.max).isoformat()
            params_range = {"from": from_dt, "to": to_dt}

            with st.spinner("Cargando métricas operativas..."):
                summary_resp = api_request("GET", "/Metrics/summary", params=params_range)
                perf_resp = api_request("GET", "/Metrics/performance", params=params_range)
                dist_resp = api_request("GET", "/Metrics/distribution", params=params_range)
                recent_resp = api_request("GET", "/Metrics/recent", params={"limit": int(ops_recent_limit)})
                feedback_stats_resp = api_request("GET", "/quality/feedback/stats", params=params_range)

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

            if feedback_stats_resp and feedback_stats_resp.status_code == 200:
                st.session_state.ops_dashboard["feedback_stats"] = feedback_stats_resp.json()
            elif feedback_stats_resp:
                render_error_response(feedback_stats_resp)

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
        ops_feedback_stats = ops_payload.get("feedback_stats", {})
        ops_recent = ops_payload.get("recent", []) or []
        ops_recent_debug = ops_payload.get("recent_debug", {}) or {}

        if not ops_summary and not ops_performance:
            st.info("Presiona 'Actualizar dashboard operativo' para cargar datos.")
        else:
            total_searches = int(ops_performance.get("totalSearches", ops_summary.get("totalSearches", 0)) or 0)
            cache_info = ops_performance.get("cache", {}) or {}
            latency_info = ops_performance.get("latency", {}) or {}
            accuracy_info = ops_performance.get("accuracy", {}) or {}

            hourly_requests_series = build_requests_per_hour(ops_recent)

            result_distribution = ops_distribution.get("resultado", ops_summary.get("resultadoDistribution", {}))
            distribution_rows = []
            distribution_totals = {"below_match": 0.0, "match": 0.0, "no_match": 0.0}
            normalized_result_aliases = {
                "below_threshold": "below_match",
            }
            label_map = {
                "below_match": "below_threshold",
                "match": "match",
                "no_match": "no match",
            }

            for key, val in (result_distribution or {}).items():
                normalized_key = str(key).strip().lower().replace(" ", "_").replace("-", "_")
                normalized_key = normalized_result_aliases.get(normalized_key, normalized_key)
                quantity = to_float(val)
                distribution_rows.append(
                    {
                        "Resultado": label_map.get(normalized_key, str(key)),
                        "ResultadoKey": normalized_key,
                        "Cantidad": quantity,
                    }
                )
                if normalized_key in distribution_totals:
                    distribution_totals[normalized_key] += quantity

            total_distribution = sum(distribution_totals.values())
            answered_match_pct = (
                (distribution_totals["match"] / total_distribution) * 100
                if total_distribution > 0
                else 0.0
            )

            positive_feedbacks = int(ops_feedback_stats.get("positiveFeedbacks", 0))
            negative_feedbacks = int(ops_feedback_stats.get("negativeFeedbacks", 0))

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Consultas totales", total_searches)
            with k2:
                st.metric("% respondidas", f"{answered_match_pct:.2f}%")
            with k3:
                st.metric("👍Feedback positivos", positive_feedbacks)
            with k4:
                st.metric("👎Feedback negativos", negative_feedbacks)

            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Requests por hora**")
                if hourly_requests_series:
                    st.line_chart(hourly_requests_series, x="hour", y="requests", use_container_width=True)
                else:
                    st.info("Sin datos suficientes para requests por hora.")

            with c2:
                st.markdown("**Distribución de resultados**")
                if result_distribution:
                    chart_rows = [row for row in distribution_rows if row.get("Cantidad", 0) > 0]

                    if chart_rows:
                        st.vega_lite_chart(
                            chart_rows,
                            {
                                "mark": {"type": "arc", "innerRadius": 50},
                                "encoding": {
                                    "theta": {"field": "Cantidad", "type": "quantitative"},
                                    "color": {
                                        "field": "ResultadoKey",
                                        "type": "nominal",
                                        "scale": {
                                            "domain": ["below_match", "match", "no_match"],
                                            "range": ["#f59e0b", "#2563eb", "#dc2626"],
                                        },
                                        "legend": {
                                            "title": "Resultado",
                                            "labelExpr": "datum.label === 'below_match' ? 'below_threshold' : datum.label",
                                        },
                                    },
                                    "tooltip": [
                                        {"field": "Resultado", "type": "nominal"},
                                        {"field": "Cantidad", "type": "quantitative"},
                                    ],
                                },
                            },
                            use_container_width=True,
                        )
                    else:
                        st.info("Sin datos positivos para graficar distribución.")

                    st.caption(
                        " | ".join(
                            [
                                f"below_threshold: {int(distribution_totals['below_match'])}",
                                f"match: {int(distribution_totals['match'])}",
                                f"no_match: {int(distribution_totals['no_match'])}",
                            ]
                        )
                    )
                else:
                    st.info("Sin datos de distribución.")

            if ops_recent:
                # st.markdown("---")
                # st.markdown("**Requests acumulados: con cache vs sin cache (por día)**")
                # cache_vs_no_cache_series = build_cache_accumulated_by_day(ops_recent)

                # st.line_chart(
                #     cache_vs_no_cache_series,
                #     x="day",
                #     y=["Con cache", "Sin cache"],
                #     use_container_width=True
                # )

                st.markdown("---")
                st.markdown("**Tendencia de latencia promedio (con/sin cache) por día**")
                latency_by_cache_series = build_latency_average_by_day(ops_recent)

                st.line_chart(
                    latency_by_cache_series,
                    x="day",
                    y=["Latencia con cache", "Latencia sin cache"],
                    use_container_width=True
                )

                st.markdown("---")
                with st.expander("📋 Ver últimas métricas (tabla)"):
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
                            for item in sorted(ops_recent, key=lambda x: x.get("timestamp", ""))
                        ],
                        use_container_width=True
                    )
            else:
                st.info("Sin datos recientes para series temporales.")

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

                g1, g2, g3, g4, g6, g7 = st.columns(6)
                with g1:
                    st.metric("Total", total_tests)
                with g2:
                    st.metric("Passed", passed)
                with g3:
                    st.metric("Failed", failed)
                with g4:
                    st.metric("Pass Rate", f"{pass_rate * 100:.1f}%")
                with g6:
                    st.metric("Score Promedio", f"{to_float(gr.get('averageScore', 0)):.3f}")
                with g7:
                    st.metric("Respuestas Inactivas", int(gr.get("inactiveAnswersReturned", 0) or 0))

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

with testing_tab1:
    st.subheader("Cola de revisión")
    st.caption("Muestreo estratificado de ítems pendientes de revisión según segmentación de riesgo.")

    # Tabla de segmentación
    st.markdown("**Segmentación de Riesgo**")
    segmentation_data = [
        {"Segmento": "🔴 Alto", "Porcentaje": "60%", "Criterio": "Feedback negativo OR no_match OR score < 0.70"},
        {"Segmento": "🟡 Medio", "Porcentaje": "30%", "Criterio": "below_threshold con score >= 0.70"},
        {"Segmento": "🟢 Bajo", "Porcentaje": "10%", "Criterio": "match / score alto"},
    ]
    st.dataframe(segmentation_data, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Input y botón de muestreo
    st.markdown("**Generar Muestreo**")
    sample_col1, sample_col2 = st.columns([1, 1])
    with sample_col1:
        sample_count = st.number_input(
            "Cantidad de ítems a muestrear",
            min_value=1,
            max_value=500,
            value=20,
            step=1,
            key="review_sample_count"
        )
    with sample_col2:
        st.write("")
        generar_muestreo = st.button("Generar muestreo", type="primary", key="btn_generar_muestreo_revision")

    if "review_queue" not in st.session_state:
        st.session_state.review_queue = []
    if "review_queue_loaded" not in st.session_state:
        st.session_state.review_queue_loaded = False
    if "review_resolved_message" not in st.session_state:
        st.session_state.review_resolved_message = None

    # Mostrar mensaje de éxito si existe
    resolved_msg = st.session_state.get("review_resolved_message")
    if resolved_msg:
        st.success(resolved_msg)
        st.session_state.review_resolved_message = None

    if generar_muestreo:
        with st.spinner(f"Generando muestreo de {sample_count} ítems..."):
            response = api_request("GET", "/qa/review-queue/sample", params={"count": int(sample_count)})

        if response and response.status_code == 200:
            payload = response.json()
            st.session_state.review_queue = payload.get("items", []) if isinstance(payload, dict) else payload
            st.session_state.review_queue_loaded = True
            st.success(f"Muestreo generado: {len(st.session_state.review_queue)} ítems")
        elif response:
            render_error_response(response)

    # Mostrar cola
    review_items = st.session_state.get("review_queue", []) or []
    
    if not review_items:
        st.info("Genera un muestreo para ver los ítems pendientes de revisión.")
    else:
        # Catálogo de respuestas para resoluciones
        respuestas_catalog = load_respuestas_catalog()
        answer_map = {
            f"{r.get('id')} [{r.get('answerKey') or 'Sin key'}]": r
            for r in respuestas_catalog
            if r.get("id")
        }

        # Mostrar cada ítem
        for idx, item in enumerate(review_items):
            item_id = item.get("id")
            query = item.get("originalQuery", item.get("query", "N/A"))
            resultado = item.get("resultado", "N/A")
            score = to_float(item.get("score", 0))
            impact_level = item.get("impactLevel", "bajo").lower()
            review_status = item.get("reviewStatus", "pendiente_revision")
            ai_draft_status = item.get("aiDraftStatus", "")
            ai_draft_answer = item.get("aiDraftAnswer", "")
            has_feedback = to_bool(item.get("hasUserFeedback", False))
            feedback_type = item.get("userFeedbackType", "")
            feedback_comment = item.get("feedbackComment", "")

            # Determinar color unificado: rojo si feedback neg o no_match, amarillo si below_threshold sin feedback neg, verde si match sin feedback neg
            if has_feedback and feedback_type == "negative":
                status_badge = "🔴"
                status_label = "Feedback negativo"
            elif resultado == "no_match":
                status_badge = "🔴"
                status_label = "Sin respuesta"
            elif resultado == "below_threshold":
                status_badge = "🟡"
                status_label = "Score bajo"
            else:
                status_badge = "🟢"
                status_label = "Match"

            title = f"{status_badge} {status_label} | {query[:80]}"

            with st.expander(title, expanded=False):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.write(f"**Query:** {query}")
                    st.write(f"**Score:** {score:.3f} | **Estado:** {review_status}")
                    st.write(f"**Resultado técnico:** {resultado}")
                    
                    # Mostrar respuesta proporcionada
                    answer_key = item.get("answerKey", "")
                    answer_text = item.get("answerText", "")
                    if answer_key or answer_text:
                        st.markdown("---")
                        if answer_key:
                            st.write(f"**Answer Key:** {answer_key}")
                        if answer_text:
                            st.write(f"**Respuesta proporcionada:** {answer_text}")
                    
                    if has_feedback:
                        st.caption(f"💬 Comentario del usuario: {feedback_comment or '(sin comentario)'}")
                    if ai_draft_status == "generada" and ai_draft_answer:
                        st.info(f"💡 Borrador IA disponible: {ai_draft_answer[:200]}...")

                with col2:
                    feedback_label = "Sin feedback" if not has_feedback else ("👍 Positivo" if feedback_type == "positive" else "👎 Negativo")
                    st.markdown(f'<p style="font-size:0.8rem;color:grey;margin-bottom:2px">Feedback</p><p style="font-size:1.25rem;font-weight:700;margin:0">{feedback_label}</p>', unsafe_allow_html=True)

                # Panel de resolución
                st.markdown("---")
                st.markdown("**Resolver**")

                # Radio button fuera del form para que rerune y muestre/oculte campos dinámicamente
                accion = st.radio(
                    "Acción",
                    ["usar_existente", "crear_nueva", "descartar"],
                    format_func=lambda x: {
                        "usar_existente": "Usar respuesta existente",
                        "crear_nueva": "Crear nueva respuesta",
                        "descartar": "Descartar (no amerita KB)"
                    }[x],
                    horizontal=True,
                    key=f"review_accion_{idx}"
                )

                # Campos según la acción (fuera del form para que se actualicen dinámicamente)
                pregunta_texto = st.text_input(
                    "Texto de pregunta (opcional)",
                    value=query,
                    key=f"review_pregunta_{idx}",
                    help="Si no se completa, se usa la query original"
                )

                respuesta_id_existente = None
                nueva_respuesta_texto = ""
                nueva_respuesta_key = ""

                if accion == "usar_existente":
                    selected_respuesta = st.selectbox(
                        "Seleccionar respuesta existente",
                        [""] + list(answer_map.keys()),
                        key=f"review_respuesta_select_{idx}"
                    )
                    if selected_respuesta:
                        respuesta_id_existente = answer_map[selected_respuesta].get("id")

                elif accion == "crear_nueva":
                    nueva_respuesta_texto = st.text_area(
                        "Texto de nueva respuesta",
                        value=ai_draft_answer,
                        height=120,
                        key=f"review_nueva_respuesta_{idx}",
                        placeholder="Escribir la nueva respuesta..."
                    )
                    nueva_respuesta_key = st.text_input(
                        "ANSWER_KEY (opcional)",
                        key=f"review_nueva_key_{idx}",
                        placeholder="EJ: SALDO_CONSULTA"
                    )

                observaciones = st.text_area(
                    "Observaciones (opcional)",
                    key=f"review_obs_{idx}",
                    height=60,
                    placeholder="Notas del revisor..."
                )

                agregar_regression = st.checkbox(
                    "Agregar al dataset de regresión",
                    value=True,
                    key=f"review_regression_{idx}"
                )

                if st.button("Guardar resolución", type="primary", key=f"review_guardar_{idx}"):
                    # Validar
                    if accion == "usar_existente" and not respuesta_id_existente:
                        st.error("Selecciona una respuesta existente")
                    elif accion == "crear_nueva" and not nueva_respuesta_texto.strip():
                        st.error("Completa el texto de la nueva respuesta")
                    elif accion == "descartar" and not observaciones.strip():
                        st.error("Completa las observaciones para descartar")
                    else:
                        # Construir payload
                        payload = {
                            "accion": accion,
                            "resueltoPor": st.session_state.get("auth_user", "streamlit-qa"),
                            "preguntaTexto": pregunta_texto.strip() if pregunta_texto.strip() else None,
                            "agregarAlRegressionDataset": agregar_regression and accion != "descartar",
                        }

                        if accion == "usar_existente":
                            payload["respuestaIdExistente"] = respuesta_id_existente
                        elif accion == "crear_nueva":
                            payload["nuevaRespuestaTexto"] = nueva_respuesta_texto.strip()
                            payload["nuevaRespuestaAnswerKey"] = (nueva_respuesta_key.strip().upper() if nueva_respuesta_key.strip() else None)
                        elif accion == "descartar":
                            payload["observaciones"] = observaciones.strip()

                        # Enviar
                        with st.spinner("Guardando resolución..."):
                            response = api_request("POST", f"/qa/review-queue/{item_id}/resolve", json=payload)

                        if response and response.status_code in (200, 201):
                            st.session_state.review_resolved_message = "✅ Resolución guardada correctamente"
                            st.session_state.review_queue_loaded = False
                            st.rerun()
                        elif response:
                            render_error_response(response)

with testing_tab2:
    st.header("Regression DataSet")
    st.caption("Listado y desactivación de entradas. Alta y edición no disponibles por ahora.")

    if "regression_entries_payload" not in st.session_state:
        st.session_state.regression_entries_payload = {"total": 0, "entries": []}
    if "regression_auto_loaded" not in st.session_state:
        st.session_state.regression_auto_loaded = False

    # Auto-load regression entries on first entry
    if not st.session_state.regression_auto_loaded:
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
            st.session_state.regression_auto_loaded = True
        elif response:
            render_error_response(response)

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

flush_browser_logs()