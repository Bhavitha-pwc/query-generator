"""Code generator panel: pick a language, describe a task, get generated code
plus evaluation metrics for that specific program. Session history lives in
memory; every generation and run outcome is also persisted via
codegen/telemetry.py (its own SQLite file, decoupled from the SQL generator's
telemetry.db) so a traceability drill-down and cross-session observability
panel both have something to show.
"""
import pandas as pd
import streamlit as st

from codegen.generate import generate_code
from codegen.languages import SUPPORTED_LANGUAGES
from codegen.metrics import evaluate_code
from codegen.runner import RunResult
from codegen.telemetry import log_trace, update_run_result


def _fmt_bool(v: bool | None) -> str:
    if v is None:
        return "—"
    return "✅ True" if v else "❌ False"


def _render_traceability(entry: dict) -> None:
    result, metrics = entry["result"], entry["metrics"]
    with st.expander(
        f"🔎 Traceability — why the pipeline did this  ·  trace `{entry.get('trace_id', 'n/a')}`",
        expanded=True,
    ):
        st.markdown("**Step 1 · Prompt construction**")
        st.markdown(
            f"- Task: _{result.task}_\n"
            f"- Target language: `{SUPPORTED_LANGUAGES[result.language].display_name}`\n"
            f"- No prompt-enhancer pass for this flow (unlike the SQL generator) — "
            f"the task is sent to the model as-is inside a language-specific system prompt."
        )

        st.markdown("**Step 2 · Code generation**")
        if result.status == "ok":
            st.markdown(
                f"- ✅ Model returned code · approach: {result.explanation or '—'}\n"
                f"- Took {result.latency_ms:.0f} ms"
            )
        elif result.status == "out_of_scope":
            st.markdown(f"- Model determined this isn't a code generation task: {result.reason}")
        else:
            st.markdown(f"- ❌ Generation failed: {result.reason}")

        st.markdown("**Step 3 · Syntax & static checks**")
        if metrics is None:
            st.markdown("- Skipped — no code was generated to check")
        elif not metrics.syntax_checker_available:
            st.markdown("- No local toolchain available to check this language's syntax")
        else:
            st.markdown(
                f"- Syntax valid: {_fmt_bool(metrics.syntax_valid)}\n"
                f"- Lint issues: {'—' if metrics.lint_issue_count is None else metrics.lint_issue_count}\n"
                f"- Compiler warnings: {'—' if metrics.warning_count is None else metrics.warning_count}"
            )

        st.markdown("**Step 4 · Run**")
        run_result: RunResult | None = entry["run_result"]
        if run_result is None:
            st.markdown("- Not run yet — use the Run section below")
        elif not run_result.available:
            st.markdown(f"- Can't run here: {run_result.error}")
        else:
            st.markdown(f"- Exit code `{run_result.exit_code}`" + (f" — {run_result.error}" if run_result.error else ""))


def _render_run_section(entry: dict, language_meta) -> None:
    """Run button + optional stdin box + output for the currently displayed
    program. Runs locally with a 10s timeout — see codegen/runner.py. The
    outcome is stored on `entry` (the history record) rather than a single
    session-wide slot, so it survives once this program stops being "latest"
    and shows up in the history table below.
    """
    result = entry["result"]
    st.markdown("**Run this program**")
    st.caption(
        "Executes the generated code locally (10s timeout). Review the code above "
        "before running, especially if it touches files or the network."
    )

    stdin_text = ""
    if language_meta.accepts_stdin:
        stdin_text = st.text_area(
            "Program input (stdin) — fill in only if the program reads input",
            key=f"stdin_{id(entry)}",
            placeholder="One value per line, if the program needs any.",
        )

    if st.button("▶ Run code", key=f"run_{id(entry)}"):
        with st.spinner("Running..."):
            entry["run_result"] = language_meta.runner(result.code, stdin_text)
            if entry.get("trace_id"):
                update_run_result(entry["trace_id"], entry["run_result"])

    run_result: RunResult | None = entry["run_result"]
    if run_result is None:
        return

    if not run_result.available:
        st.warning(f"Can't run {language_meta.display_name} here: {run_result.error}")
        return
    if run_result.error:
        st.error(run_result.error)
    if run_result.timed_out:
        st.error(run_result.error)
        return

    st.markdown(f"Exit code: `{run_result.exit_code}`")
    if run_result.stdout:
        st.markdown("Output:")
        st.code(run_result.stdout, language="text")
    if run_result.stderr:
        st.markdown("Errors/stderr:")
        st.code(run_result.stderr, language="text")
    if not run_result.stdout and not run_result.stderr:
        st.caption("Program produced no output.")


def render_codegen_history_panel() -> None:
    """Short-term memory: session-scoped generation history (this browser
    session only, lost on refresh/restart). The persisted, cross-session
    equivalent lives in codegen_observability_panel.py.
    """
    st.caption("Every program generated in this browser session, most recent first.")
    st.caption("📍 Stored in `st.session_state.codegen_history` — server RAM, this browser session only.")
    if not st.session_state.get("codegen_history"):
        st.caption("No programs generated yet.")
        return

    hist_rows = []
    for entry in st.session_state.codegen_history:
        r, mm, rr = entry["result"], entry["metrics"], entry["run_result"]
        hist_rows.append({
            "task": r.task if len(r.task) <= 60 else r.task[:57] + "...",
            "language": SUPPORTED_LANGUAGES[r.language].display_name,
            "status": r.status,
            "syntax_valid": mm.syntax_valid if mm else None,
            "lint_issues": mm.lint_issue_count if mm else None,
            "warnings": mm.warning_count if mm else None,
            "lines_of_code": mm.lines_of_code if mm else None,
            "latency_ms": round(r.latency_ms, 0),
            "ran": rr is not None,
            "run_exit_code": rr.exit_code if rr else None,
        })
    st.dataframe(pd.DataFrame(hist_rows), use_container_width=True)


def render_codegen_panel() -> None:
    st.subheader("Generate a program", divider="blue")
    st.caption(
        "Describe a task, pick a target language, and get generated code plus "
        "evaluation metrics for that specific program (syntax validity, lint "
        "issues/compiler warnings where supported, size, latency)."
    )

    if "codegen_history" not in st.session_state:
        st.session_state.codegen_history = []  # list[dict(result, metrics, run_result)]

    lang_keys = list(SUPPORTED_LANGUAGES.keys())
    language = st.selectbox(
        "Target language", lang_keys,
        format_func=lambda k: SUPPORTED_LANGUAGES[k].display_name,
    )
    task = st.text_area(
        "Task description",
        placeholder="e.g. Write a function that returns the nth Fibonacci number.",
    )
    generate = st.button("Generate code", type="primary")

    if generate and task.strip():
        with st.spinner("Generating..."):
            result = generate_code(task.strip(), language)
            metrics = (
                evaluate_code(language, result.code, result.latency_ms)
                if result.status == "ok" and result.code
                else None
            )
            trace_id = log_trace(result, metrics)
        st.session_state.codegen_history.insert(
            0, {"result": result, "metrics": metrics, "run_result": None, "trace_id": trace_id}
        )

    if not st.session_state.codegen_history:
        return

    latest_entry = st.session_state.codegen_history[0]
    latest_result, latest_metrics = latest_entry["result"], latest_entry["metrics"]
    lang_display = SUPPORTED_LANGUAGES[latest_result.language].display_name

    if latest_result.status == "out_of_scope":
        st.warning(f"Refused — not a code generation task: {latest_result.reason or ''}")
        _render_traceability(latest_entry)
        return
    if latest_result.status == "error":
        st.error(f"Generation error: {latest_result.reason}")
        _render_traceability(latest_entry)
        return

    st.code(latest_result.code, language=SUPPORTED_LANGUAGES[latest_result.language].streamlit_lexer)
    if latest_result.explanation:
        st.caption(f"Approach: {latest_result.explanation}")

    _render_traceability(latest_entry)

    st.markdown(f"**Evaluation metrics for this {lang_display} program**")
    m = latest_metrics
    m_cols = st.columns(6)
    if m.syntax_checker_available:
        m_cols[0].metric("Syntax valid", _fmt_bool(m.syntax_valid))
    else:
        m_cols[0].metric("Syntax valid", "n/a")
        m_cols[0].caption("No local toolchain to check this language")
    m_cols[1].metric("Lint issues", "—" if m.lint_issue_count is None else str(m.lint_issue_count))
    m_cols[2].metric("Warnings", "—" if m.warning_count is None else str(m.warning_count))
    m_cols[3].metric("Lines of code", m.lines_of_code)
    m_cols[4].metric("Approx tokens", m.approx_token_count)
    m_cols[5].metric("Latency", f"{m.latency_ms:.0f} ms")

    if m.syntax_error:
        with st.expander("Syntax check details"):
            st.code(m.syntax_error)

    st.divider()
    _render_run_section(latest_entry, language_meta=SUPPORTED_LANGUAGES[latest_result.language])
