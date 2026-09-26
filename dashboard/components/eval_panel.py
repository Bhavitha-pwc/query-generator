"""Gold-query suite evaluation panel: aggregate metric tiles, per-query status
chart, and a raw metrics table.
"""
import altair as alt
import pandas as pd
import streamlit as st

from nl2sql.evaluate import run_suite
from nl2sql.metrics import aggregate

from dashboard.status import status_color, status_label
from dashboard.theme import COLOR_CRITICAL, COLOR_GOOD, COLOR_MUTED, TEXT_SECONDARY


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def render_eval_panel() -> None:
    st.subheader("Evaluation metrics", divider="orange")
    st.caption(
        "Run the labeled gold-query suite (data/gold_queries.json) to score the "
        "generator end to end."
    )

    if st.button("Run evaluation suite"):
        with st.spinner("Running gold query suite..."):
            st.session_state.suite_results = run_suite()

    results = st.session_state.suite_results
    if not results:
        st.info("No evaluation run yet — click **Run evaluation suite** above.")
        return

    agg = aggregate(results)

    tiles = st.columns(6)
    tiles[0].metric("Execution accuracy", _fmt_pct(agg["execution_accuracy"]))
    tiles[1].metric("Exact match", _fmt_pct(agg["exact_match"]))
    tiles[2].metric("Component F1", _fmt_pct(agg["component_f1"]))
    tiles[3].metric("Valid SQL rate", _fmt_pct(agg["valid_sql_rate"]))
    tiles[4].metric("Out-of-scope rejection", _fmt_pct(agg["out_of_scope_rejection_rate"]))
    tiles[5].metric("Avg latency", f"{agg['avg_latency_ms']:.0f} ms")

    st.markdown("**Per-query results**")
    rows = []
    for m in results:
        label = status_label(m)
        rows.append({
            "question": m.question if len(m.question) <= 60 else m.question[:57] + "...",
            "status": label,
            "color": status_color(label),
        })
    df = pd.DataFrame(rows)

    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4, size=18)
        .encode(
            y=alt.Y("question:N", sort=None, title=None,
                    axis=alt.Axis(labelColor=TEXT_SECONDARY, labelLimit=280)),
            x=alt.X("count():Q", title=None, axis=None, scale=alt.Scale(domain=[0, 1])),
            color=alt.Color(
                "status:N",
                scale=alt.Scale(
                    domain=["Pass", "Correctly refused", "Fail", "Error",
                            "Invalid SQL", "Incorrectly refused", "Ungraded"],
                    range=[COLOR_GOOD, COLOR_GOOD, COLOR_CRITICAL, COLOR_CRITICAL,
                           COLOR_CRITICAL, COLOR_CRITICAL, COLOR_MUTED],
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=["question", "status"],
        )
        .properties(height=28 * len(df) + 40)
        .configure_axis(grid=False)
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)

    with st.expander("Raw per-query metrics & trace"):
        detail_rows = [{
            "question": m.question,
            "status": status_label(m),
            "execution_accuracy": m.execution_accuracy,
            "exact_match": m.exact_match,
            "component_f1": None if m.component_f1 is None else round(m.component_f1, 2),
            "latency_ms": round(m.latency_ms, 0),
            "prompt_enhanced": m.prompt_enhanced,
            "tables_used": ", ".join(m.tables_used),
            "confidence": m.confidence,
            "explanation": m.explanation,
            "generated_sql": m.generated_sql,
        } for m in results]
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True)
