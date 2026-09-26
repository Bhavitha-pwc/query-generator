"""Ask-a-question panel: input box, generated SQL + results, and the per-query
traceability/metrics drill-down for the most recent question.
"""
import streamlit as st

from nl2sql.evaluate import evaluate_question, find_gold, load_gold
from nl2sql.metrics import QueryMetrics

from dashboard.status import status_color, status_label
from dashboard.theme import CONFIDENCE_COLOR, COLOR_MUTED


def _fmt_bool(v: bool | None) -> str:
    if v is None:
        return "—"
    return "✅ True" if v else "❌ False"


def _render_traceability(latest: QueryMetrics) -> None:
    with st.expander(
        f"🔎 Traceability — why the pipeline did this  ·  trace `{latest.trace_id}`",
        expanded=True,
    ):
        st.markdown("**Step 1 · Prompt enhancement**")
        if latest.prompt_enhanced:
            st.markdown(
                f"- Your question: _{latest.question}_\n"
                f"- Rewritten to: _{latest.enhanced_question}_\n"
                f"- Why: {latest.enhance_reason}\n"
                f"- Took {latest.enhance_latency_ms:.0f} ms"
            )
        else:
            st.markdown(
                f"- No rewrite needed ({latest.enhance_reason or 'already clear'}), "
                f"sent as-is. Took {latest.enhance_latency_ms:.0f} ms"
            )

        st.markdown("**Step 2 · Schema grounding & SQL generation**")
        if latest.status == "ok":
            tables_badge = ", ".join(f"`{t}`" for t in latest.tables_used) or "—"
            conf = latest.confidence or "unknown"
            conf_color = CONFIDENCE_COLOR.get(conf, COLOR_MUTED)
            st.markdown(
                f"- Tables grounded on: {tables_badge}\n"
                f"- Model's self-reported confidence: "
                f"<span style='color:{conf_color}; font-weight:600;'>{conf}</span>\n"
                f"- Reasoning: {latest.explanation or '—'}\n"
                f"- Took {(latest.latency_ms - latest.enhance_latency_ms):.0f} ms",
                unsafe_allow_html=True,
            )
        elif latest.status == "out_of_scope":
            st.markdown(f"- Model determined this needs data outside the schema: {latest.reason}")
        else:
            st.markdown(f"- Generation failed: {latest.error}")

        st.markdown("**Step 3 · Execution**")
        if latest.status == "ok":
            if latest.error:
                st.markdown(f"- ❌ Execution failed: {latest.error}")
            else:
                st.markdown(f"- ✅ Ran against `synthetic.db`, returned {len(latest.generated_rows)} row(s)")
        else:
            st.markdown("- Skipped — no SQL was generated to run")

        st.markdown("**Step 4 · Evaluation** — see the metrics row below")


def render_query_panel() -> None:
    import pandas as pd

    st.subheader("Ask a question", divider="blue")
    question = st.text_input(
        "English question",
        placeholder="e.g. Which customers have never placed an order?",
    )
    ask = st.button("Generate SQL", type="primary")

    if ask and question.strip():
        gold_set = load_gold()
        with st.spinner("Generating..."):
            metrics = evaluate_question(question.strip(), gold_set)
        st.session_state.history.insert(0, metrics)

    if not st.session_state.history:
        return

    latest = st.session_state.history[0]
    label = status_label(latest)
    color = status_color(label)

    st.markdown(
        f"<span style='color:{color}; font-weight:600;'>● {label}</span>",
        unsafe_allow_html=True,
    )

    if latest.status == "out_of_scope":
        st.warning(f"Refused as out-of-scope: {latest.reason or ''}")
    elif latest.status == "error":
        st.error(f"Generation error: {latest.error}")
    elif latest.generated_sql:
        st.code(latest.generated_sql, language="sql")
        if latest.error:
            st.error(f"Execution error: {latest.error}")
        elif latest.generated_rows is not None:
            df = pd.DataFrame(latest.generated_rows, columns=latest.generated_columns)
            st.dataframe(df, use_container_width=True)

    _render_traceability(latest)

    st.markdown("**Metrics for this query**")
    m_cols = st.columns(5)
    m_cols[0].metric("Valid SQL", _fmt_bool(latest.valid_sql if latest.status == "ok" else None))
    m_cols[1].metric("Execution accuracy", _fmt_bool(latest.execution_accuracy))
    m_cols[2].metric("Exact match", _fmt_bool(latest.exact_match))
    m_cols[3].metric(
        "Component F1",
        "—" if latest.component_f1 is None else f"{latest.component_f1:.2f}",
    )
    m_cols[4].metric("Latency", f"{latest.latency_ms:.0f} ms")

    if latest.gold_sql is None and latest.status != "out_of_scope":
        st.caption(
            "No gold reference for this question — Valid SQL and Latency are "
            "graded, Execution Accuracy / Exact Match / Component F1 need a "
            "labeled entry in data/gold_queries.json to compare against."
        )

    gold_entry = find_gold(latest.question, load_gold())
    if gold_entry and gold_entry.get("gold_sql"):
        with st.expander("Gold reference query"):
            st.code(gold_entry["gold_sql"], language="sql")
