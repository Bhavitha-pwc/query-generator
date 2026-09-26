"""Persisted observability layer: every generation request is written here as
a structured trace row, independent of any one Streamlit session, so history
survives restarts and can be aggregated (error rate, latency trend, etc.).

This is app telemetry, not domain data — kept in its own SQLite file, separate
from data/synthetic.db, so it's never mistaken for part of the queryable schema.
"""
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from common.config import TELEMETRY_DB_PATH as DB_PATH
from nl2sql.metrics import QueryMetrics

logger = logging.getLogger("nl2sql.telemetry")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id            TEXT PRIMARY KEY,
    ts                  TEXT NOT NULL,
    source              TEXT NOT NULL,   -- "interactive" | "suite"
    question            TEXT NOT NULL,
    enhanced_question    TEXT,
    prompt_enhanced      INTEGER,
    enhance_reason       TEXT,
    enhance_latency_ms   REAL,
    status              TEXT NOT NULL,   -- ok | out_of_scope | error
    generated_sql        TEXT,
    tables_used          TEXT,           -- JSON list
    confidence           TEXT,
    explanation          TEXT,
    valid_sql            INTEGER,
    execution_accuracy   INTEGER,        -- nullable tri-state via NULL
    exact_match          INTEGER,
    component_f1         REAL,
    out_of_scope_correct INTEGER,
    latency_ms           REAL NOT NULL,
    error               TEXT,
    reason              TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def _bool_to_int(v: bool | None) -> int | None:
    return None if v is None else int(v)


def log_trace(metrics: QueryMetrics, source: str = "interactive") -> str:
    """Persist one completed pipeline run and return its trace_id."""
    trace_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).isoformat()

    conn = _connect()
    conn.execute(
        """INSERT INTO traces (
            trace_id, ts, source, question, enhanced_question, prompt_enhanced,
            enhance_reason, enhance_latency_ms, status, generated_sql, tables_used,
            confidence, explanation, valid_sql, execution_accuracy, exact_match,
            component_f1, out_of_scope_correct, latency_ms, error, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trace_id, ts, source, metrics.question, metrics.enhanced_question,
            _bool_to_int(metrics.prompt_enhanced), metrics.enhance_reason,
            metrics.enhance_latency_ms, metrics.status, metrics.generated_sql,
            json.dumps(metrics.tables_used), metrics.confidence, metrics.explanation,
            _bool_to_int(metrics.valid_sql), _bool_to_int(metrics.execution_accuracy),
            _bool_to_int(metrics.exact_match), metrics.component_f1,
            _bool_to_int(metrics.out_of_scope_correct), metrics.latency_ms,
            metrics.error, metrics.reason,
        ),
    )
    conn.commit()
    conn.close()

    logger.info(
        "trace_id=%s source=%s status=%s valid_sql=%s ex=%s latency_ms=%.0f question=%r",
        trace_id, source, metrics.status, metrics.valid_sql,
        metrics.execution_accuracy, metrics.latency_ms, metrics.question,
    )
    return trace_id


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
        d["tables_used"] = json.loads(d["tables_used"]) if d["tables_used"] else []
        for bool_field in ("prompt_enhanced", "valid_sql", "execution_accuracy",
                           "exact_match", "out_of_scope_correct"):
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

    ok_traces = [t for t in traces if t["status"] == "ok"]

    return {
        "n_requests": n,
        "error_rate": rate(lambda t: t["status"] == "error"),
        "out_of_scope_rate": rate(lambda t: t["status"] == "out_of_scope"),
        "valid_sql_rate": (
            sum(1 for t in ok_traces if t["valid_sql"]) / len(ok_traces)
            if ok_traces else None
        ),
        "prompt_enhanced_rate": rate(lambda t: t["prompt_enhanced"]),
        "avg_latency_ms": sum(latencies) / n,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
    }
