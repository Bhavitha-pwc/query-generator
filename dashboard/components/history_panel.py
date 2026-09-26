"""Short-term memory: session-scoped query history (this browser session only,
lost on refresh/restart). The persisted, cross-session equivalent lives in
observability_panel.py.
"""
import pandas as pd
import streamlit as st

from dashboard.status import status_label


def render_history_panel() -> None:
    st.caption("Every question asked in this browser session, most recent first.")
    st.caption("📍 Stored in `st.session_state.history` — server RAM, this browser session only.")
    if not st.session_state.history:
        st.caption("No questions asked yet.")
        return

    hist_rows = [{
        "question": m.question,
        "prompt_enhanced": m.prompt_enhanced,
        "status": status_label(m),
        "valid_sql": m.valid_sql if m.status == "ok" else None,
        "execution_accuracy": m.execution_accuracy,
        "exact_match": m.exact_match,
        "component_f1": None if m.component_f1 is None else round(m.component_f1, 2),
        "latency_ms": round(m.latency_ms, 0),
        "sql": m.generated_sql or "",
        "explanation": m.explanation or "",
    } for m in st.session_state.history]
    st.dataframe(pd.DataFrame(hist_rows), use_container_width=True)
