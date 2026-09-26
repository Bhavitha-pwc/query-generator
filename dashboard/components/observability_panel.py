"""Long-term memory: persisted-trace observability panel — KPIs + latency/status
charts across every request from every session/process (data/telemetry.db),
independent of the current browser session's in-memory history in
history_panel.py.
"""
import altair as alt
import pandas as pd
import streamlit as st

from common.config import TELEMETRY_DB_PATH
from nl2sql.telemetry import aggregate_traces, clear_traces, load_traces

from dashboard.theme import COLOR_CRITICAL, COLOR_GOOD, COLOR_MUTED


def render_observability_panel() -> None:
    st.caption("Persisted trace history across all sessions — survives dashboard restarts.")
    st.caption(f"📍 Stored in `{TELEMETRY_DB_PATH}` — SQLite file on disk, `traces` table.")

    traces = load_traces()
    if not traces:
        st.info("No traces recorded yet — ask a question above to generate one.")
        return

    kpis = aggregate_traces(traces)

    kpi_cols = st.columns(6)
    kpi_cols[0].metric("Requests", kpis["n_requests"])
    kpi_cols[1].metric("Error rate", f"{kpis['error_rate']:.0%}")
    kpi_cols[2].metric("Out-of-scope rate", f"{kpis['out_of_scope_rate']:.0%}")
    kpi_cols[3].metric(
        "Valid SQL rate",
        "—" if kpis["valid_sql_rate"] is None else f"{kpis['valid_sql_rate']:.0%}",
    )
    kpi_cols[4].metric("Prompt-enhanced rate", f"{kpis['prompt_enhanced_rate']:.0%}")
    kpi_cols[5].metric(
        "Latency avg / p50 / p95",
        f"{kpis['avg_latency_ms']:.0f} / {kpis['p50_latency_ms']:.0f} / {kpis['p95_latency_ms']:.0f} ms",
    )

    trace_df = pd.DataFrame(traces)
    trace_df["ts"] = pd.to_datetime(trace_df["ts"])

    chart_col, dist_col = st.columns([2, 1])

    with chart_col:
        st.caption("Latency over time")
        latency_chart = (
            alt.Chart(trace_df)
            .mark_line(point=True, color="#3b7dd8", strokeWidth=2)
            .encode(
                x=alt.X("ts:T", title=None),
                y=alt.Y("latency_ms:Q", title="Latency (ms)"),
                tooltip=["ts:T", "question:N", "latency_ms:Q", "status:N"],
            )
            .properties(height=220)
        )
        st.altair_chart(latency_chart, use_container_width=True)

    with dist_col:
        st.caption("Status distribution")
        status_counts = trace_df["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        status_domain = ["ok", "out_of_scope", "error"]
        status_range = [COLOR_GOOD, COLOR_MUTED, COLOR_CRITICAL]
        status_chart = (
            alt.Chart(status_counts)
            .mark_bar()
            .encode(
                x=alt.X("count:Q", title=None),
                y=alt.Y("status:N", title=None, sort=status_domain),
                color=alt.Color(
                    "status:N",
                    scale=alt.Scale(domain=status_domain, range=status_range),
                    legend=None,
                ),
                tooltip=["status:N", "count:Q"],
            )
            .properties(height=220)
        )
        st.altair_chart(status_chart, use_container_width=True)

    with st.expander(f"All persisted traces ({len(traces)})"):
        search = st.text_input("Filter by question text", key="trace_filter")
        rows = [{
            "trace_id": t["trace_id"],
            "ts": t["ts"],
            "source": t["source"],
            "question": t["question"],
            "status": t["status"],
            "prompt_enhanced": t["prompt_enhanced"],
            "valid_sql": t["valid_sql"],
            "execution_accuracy": t["execution_accuracy"],
            "confidence": t["confidence"],
            "latency_ms": round(t["latency_ms"], 0),
            "generated_sql": t["generated_sql"],
        } for t in traces if not search or search.lower() in t["question"].lower()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        if st.button("Clear persisted trace history", type="secondary"):
            clear_traces()
            st.rerun()
