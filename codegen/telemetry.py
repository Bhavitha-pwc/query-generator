"""Persisted observability layer for the code generator: every generation
request is written here as a structured trace row, independent of any one
Streamlit session, so history survives restarts and can be aggregated (error
rate, syntax-valid rate, latency trend, etc.) — mirrors nl2sql/telemetry.py's
approach, but kept in its own SQLite file since codegen is decoupled from the
SQL generator.
"""
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from common.config import CODEGEN_TELEMETRY_DB_PATH as DB_PATH
from codegen.generate import CodeGenResult
from codegen.metrics import CodeMetrics
from codegen.runner import RunResult

logger = logging.getLogger("codegen.telemetry")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id                  TEXT PRIMARY KEY,
    ts                        TEXT NOT NULL,
    source                    TEXT NOT NULL,   -- "interactive"
    task                      TEXT NOT NULL,
    language                  TEXT NOT NULL,
    status                    TEXT NOT NULL,   -- ok | out_of_scope | error
    explanation               TEXT,
    reason                    TEXT,
    generated_code             TEXT,
    syntax_checker_available   INTEGER,
    syntax_valid               INTEGER,        -- nullable tri-state via NULL
    syntax_error               TEXT,
    lint_issue_count           INTEGER,
    warning_count              INTEGER,
    lines_of_code              INTEGER,
    char_count                 INTEGER,
    approx_token_count         INTEGER,
    latency_ms                 REAL NOT NULL,
    ran                       INTEGER NOT NULL DEFAULT 0,
    run_exit_code              INTEGER,
    run_error                  TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def _bool_to_int(v: bool | None) -> int | None:
    return None if v is None else int(v)


def log_trace(result: CodeGenResult, metrics: CodeMetrics | None, source: str = "interactive") -> str:
    """Persist one completed generation and return its trace_id."""
    trace_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).isoformat()

    conn = _connect()
    conn.execute(
        """INSERT INTO traces (
            trace_id, ts, source, task, language, status, explanation, reason,
            generated_code, syntax_checker_available, syntax_valid, syntax_error,
            lint_issue_count, warning_count, lines_of_code, char_count,
            approx_token_count, latency_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trace_id, ts, source, result.task, result.language, result.status,
            result.explanation, result.reason, result.code,
            _bool_to_int(metrics.syntax_checker_available) if metrics else None,
            _bool_to_int(metrics.syntax_valid) if metrics else None,
            metrics.syntax_error if metrics else None,
            metrics.lint_issue_count if metrics else None,
            metrics.warning_count if metrics else None,
            metrics.lines_of_code if metrics else None,
            metrics.char_count if metrics else None,
            metrics.approx_token_count if metrics else None,
            result.latency_ms,
        ),
    )
    conn.commit()
    conn.close()

    logger.info(
        "trace_id=%s status=%s language=%s syntax_valid=%s latency_ms=%.0f task=%r",
        trace_id, result.status, result.language,
        metrics.syntax_valid if metrics else None, result.latency_ms, result.task,
    )
    return trace_id


def update_run_result(trace_id: str, run_result: RunResult) -> None:
    """Attach a Run-button outcome to an already-persisted trace."""
    conn = _connect()
    conn.execute(
        "UPDATE traces SET ran = 1, run_exit_code = ?, run_error = ? WHERE trace_id = ?",
        (run_result.exit_code, run_result.error, trace_id),
    )
    conn.commit()
    conn.close()
    logger.info("trace_id=%s run exit_code=%s", trace_id, run_result.exit_code)


def load_traces(limit: int = 500) -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM traces ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    out = []
    for row in rows:
        d = dict(row)
        for bool_field in ("syntax_checker_available", "syntax_valid", "ran"):
            d[bool_field] = None if d[bool_field] is None else bool(d[bool_field])
        out.append(d)
    return out


def clear_traces() -> None:
    conn = _connect()
    conn.execute("DELETE FROM traces")
    conn.commit()
    conn.close()


def aggregate_traces(traces: list[dict]) -> dict:
    """Aggregate KPIs across persisted traces, for the observability panel."""
    n = len(traces)
    if n == 0:
        return {}

    def rate(pred) -> float:
        return sum(1 for t in traces if pred(t)) / n

    latencies = sorted(t["latency_ms"] for t in traces)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]

    checkable = [t for t in traces if t["syntax_checker_available"]]
    ran = [t for t in traces if t["ran"]]

    return {
        "n_requests": n,
        "error_rate": rate(lambda t: t["status"] == "error"),
        "out_of_scope_rate": rate(lambda t: t["status"] == "out_of_scope"),
        "syntax_valid_rate": (
            sum(1 for t in checkable if t["syntax_valid"]) / len(checkable)
            if checkable else None
        ),
        "run_rate": len(ran) / n,
        "run_success_rate": (
            sum(1 for t in ran if t["run_exit_code"] == 0) / len(ran) if ran else None
        ),
        "avg_latency_ms": sum(latencies) / n,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
    }
