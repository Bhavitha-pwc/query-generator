"""Streamlit dashboard: English-to-SQL generator + multi-language code generator.

Run locally with:  streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.components.codegen_observability_panel import render_codegen_observability_panel
from dashboard.components.codegen_panel import render_codegen_history_panel, render_codegen_panel
from dashboard.components.eval_panel import render_eval_panel
from dashboard.components.history_panel import render_history_panel
from dashboard.components.observability_panel import render_observability_panel
from dashboard.components.query_panel import render_query_panel
from dashboard.components.schema_panel import render_schema_panel

st.set_page_config(page_title="English → SQL Generator", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []  # list[QueryMetrics]
if "suite_results" not in st.session_state:
    st.session_state.suite_results = None


def render_sql_tab() -> None:
    st.title("English → SQL Generator")
    st.caption(
        "Ask a question in English about the synthetic retail dataset below. "
        "Questions outside the schema are refused, not guessed at."
    )

    col_main, col_schema = st.columns([2, 1])
    with col_schema:
        with st.container(border=True):
            render_schema_panel()
    with col_main:
        with st.container(border=True):
            render_query_panel()

    with st.container(border=True):
        render_eval_panel()

    st.subheader("Memory", divider="violet")
    st.caption(
        "Short-term = this browser tab only, lost on refresh. "
        "Long-term = persisted to SQLite, survives dashboard restarts."
    )
    mem_short, mem_long = st.tabs(["🧠 Short-term (session)", "💾 Long-term (persisted)"])
    with mem_short:
        render_history_panel()
    with mem_long:
        render_observability_panel()


def render_codegen_tab() -> None:
    st.title("Code Generator")
    st.caption(
        "Describe a task in English, pick a target language, and get generated "
        "code plus per-program evaluation metrics."
    )
    with st.container(border=True):
        render_codegen_panel()

    st.subheader("Memory", divider="violet")
    st.caption(
        "Short-term = this browser tab only, lost on refresh. "
        "Long-term = persisted to SQLite, survives dashboard restarts."
    )
    mem_short, mem_long = st.tabs(["🧠 Short-term (session)", "💾 Long-term (persisted)"])
    with mem_short:
        render_codegen_history_panel()
    with mem_long:
        render_codegen_observability_panel()


sql_tab, codegen_tab = st.tabs(["English → SQL", "Code Generator"])
with sql_tab:
    render_sql_tab()
with codegen_tab:
    render_codegen_tab()
