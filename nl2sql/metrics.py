"""Metric definitions used by evaluate.py and the dashboard.

See CLAUDE.md "Evaluation metrics" for the definition of each metric.
"""
import re
from dataclasses import dataclass, field

from nl2sql.execute import ExecutionResult, run_query

_CLAUSE_KEYWORDS = ["SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT"]


@dataclass
class QueryMetrics:
    question: str
    generated_sql: str | None
    gold_sql: str | None
    status: str                     # ok | out_of_scope | error
    valid_sql: bool
    execution_accuracy: bool | None  # None when no gold to compare against
    exact_match: bool | None
    component_f1: float | None
    out_of_scope_correct: bool | None  # only meaningful when gold expects OUT_OF_SCOPE
    latency_ms: float
    error: str | None = None
    reason: str | None = None
    explanation: str | None = None       # model's stated rationale for the query
    tables_used: list = field(default_factory=list)
    confidence: str | None = None        # "high" | "medium" | "low", self-reported
    enhanced_question: str | None = None  # question actually sent to the model
    prompt_enhanced: bool = False
    enhance_reason: str | None = None    # why the enhancer changed it (or didn't)
    enhance_latency_ms: float = 0.0
    generated_rows: list = field(default_factory=list)
    generated_columns: list = field(default_factory=list)
    trace_id: str | None = None  # set by telemetry.log_trace once persisted


def _normalize_sql(sql: str) -> str:
    sql = sql.strip().rstrip(";").lower()
    sql = re.sub(r"\s+", " ", sql)
    sql = re.sub(r"\s*([(),])\s*", r"\1", sql)
    return sql.strip()


def _split_clauses(sql: str) -> dict[str, str]:
    """Best-effort split of a single SELECT statement into clause bodies."""
    pattern = "|".join(_CLAUSE_KEYWORDS)
    tokens = re.split(f"(?i)\\b({pattern})\\b", sql)
    clauses: dict[str, str] = {}
    current = None
    for tok in tokens:
        tok_stripped = tok.strip()
        if tok_stripped.upper() in _CLAUSE_KEYWORDS:
            current = tok_stripped.upper()
            clauses.setdefault(current, "")
        elif current:
            clauses[current] += tok
    return {k: v.strip() for k, v in clauses.items()}


def _tokenize_clause(text: str) -> set[str]:
    if not text:
        return set()
    parts = re.split(r"[,\s]+", text.strip())
    return {p for p in parts if p}


def exact_match(generated_sql: str, gold_sql: str) -> bool:
    return _normalize_sql(generated_sql) == _normalize_sql(gold_sql)


def component_f1(generated_sql: str, gold_sql: str) -> float:
    gen_clauses = _split_clauses(_normalize_sql(generated_sql))
    gold_clauses = _split_clauses(_normalize_sql(gold_sql))

    all_keys = set(gen_clauses) | set(gold_clauses)
    if not all_keys:
        return 1.0

    scores = []
    for key in all_keys:
        gen_tokens = _tokenize_clause(gen_clauses.get(key, ""))
        gold_tokens = _tokenize_clause(gold_clauses.get(key, ""))
        if not gen_tokens and not gold_tokens:
            scores.append(1.0)
            continue
        if not gen_tokens or not gold_tokens:
            scores.append(0.0)
            continue
        overlap = gen_tokens & gold_tokens
        precision = len(overlap) / len(gen_tokens)
        recall = len(overlap) / len(gold_tokens)
        if precision + recall == 0:
            scores.append(0.0)
        else:
            scores.append(2 * precision * recall / (precision + recall))
    return sum(scores) / len(scores)


def _project(result: ExecutionResult, columns: list[str]) -> list[tuple]:
    """Reorder/narrow result rows down to the given column names."""
    indices = [result.columns.index(c) for c in columns]
    return [tuple(row[i] for i in indices) for row in result.rows]


def _rows_match(a: ExecutionResult, b: ExecutionResult, order_sensitive: bool) -> bool:
    if not (a.ok and b.ok):
        return False

    a_rows, b_rows = a.rows, b.rows
    a_cols, b_cols = set(a.columns), set(b.columns)

    # A generated query answering the same question with extra/reordered columns
    # (e.g. SELECT * instead of naming columns) is still correct — compare on
    # whichever column name set is the common subset, when one side is a superset.
    if a.columns != b.columns and a_cols != b_cols:
        if b_cols <= a_cols:
            a_rows = _project(a, b.columns)
        elif a_cols <= b_cols:
            b_rows = _project(b, a.columns)
    elif a.columns != b.columns:
        a_rows = _project(a, b.columns)

    if order_sensitive:
        return a_rows == b_rows
    return sorted(map(tuple, a_rows)) == sorted(map(tuple, b_rows))


def execution_accuracy(generated_sql: str, gold_sql: str, question: str) -> tuple[bool, ExecutionResult]:
    gen_result = run_query(generated_sql)
    gold_result = run_query(gold_sql)
    order_sensitive = "order by" in gold_sql.lower()
    return _rows_match(gen_result, gold_result, order_sensitive), gen_result


def evaluate_single(question: str, generated_sql: str | None, status: str,
                     latency_ms: float, gold_sql: str | None = None,
                     expected: str | None = None, reason: str | None = None,
                     error: str | None = None, explanation: str | None = None,
                     tables_used: list | None = None, confidence: str | None = None,
                     enhanced_question: str | None = None, prompt_enhanced: bool = False,
                     enhance_reason: str | None = None,
                     enhance_latency_ms: float = 0.0) -> QueryMetrics:
    """Score one generated result. gold_sql/expected come from gold_queries.json
    when the question matches a labeled fixture; both are None for free-form
    dashboard queries with no ground truth (only valid_sql/status are meaningful).
    """
    valid_sql = False
    generated_rows: list = []
    generated_columns: list = []

    if status == "ok" and generated_sql:
        exec_result = run_query(generated_sql)
        valid_sql = exec_result.ok
        error = exec_result.error
        generated_rows = exec_result.rows
        generated_columns = exec_result.columns

    out_of_scope_correct = None
    if expected == "OUT_OF_SCOPE":
        out_of_scope_correct = status == "out_of_scope"

    ex = em = f1 = None
    if gold_sql and status == "ok" and generated_sql:
        ex, _ = execution_accuracy(generated_sql, gold_sql, question)
        em = exact_match(generated_sql, gold_sql)
        f1 = component_f1(generated_sql, gold_sql)

    return QueryMetrics(
        question=question,
        generated_sql=generated_sql,
        gold_sql=gold_sql,
        status=status,
        valid_sql=valid_sql,
        execution_accuracy=ex,
        exact_match=em,
        component_f1=f1,
        out_of_scope_correct=out_of_scope_correct,
        latency_ms=latency_ms,
        error=error,
        reason=reason,
        explanation=explanation,
        tables_used=tables_used or [],
        confidence=confidence,
        enhanced_question=enhanced_question,
        prompt_enhanced=prompt_enhanced,
        enhance_reason=enhance_reason,
        enhance_latency_ms=enhance_latency_ms,
        generated_rows=generated_rows,
        generated_columns=generated_columns,
    )


def aggregate(metrics: list[QueryMetrics]) -> dict:
    """Aggregate metrics across a run for the dashboard's summary panel."""
    n = len(metrics)
    if n == 0:
        return {}

    def rate(pred) -> float | None:
        applicable = [m for m in metrics if pred(m) is not None]
        if not applicable:
            return None
        return sum(1 for m in applicable if pred(m)) / len(applicable)

    ex_applicable = [m for m in metrics if m.execution_accuracy is not None]
    em_applicable = [m for m in metrics if m.exact_match is not None]
    f1_applicable = [m for m in metrics if m.component_f1 is not None]
    oos_applicable = [m for m in metrics if m.out_of_scope_correct is not None]

    return {
        "n_queries": n,
        "valid_sql_rate": sum(1 for m in metrics if m.valid_sql) / n,
        "execution_accuracy": (
            sum(1 for m in ex_applicable if m.execution_accuracy) / len(ex_applicable)
            if ex_applicable else None
        ),
        "exact_match": (
            sum(1 for m in em_applicable if m.exact_match) / len(em_applicable)
            if em_applicable else None
        ),
        "component_f1": (
            sum(m.component_f1 for m in f1_applicable) / len(f1_applicable)
            if f1_applicable else None
        ),
        "out_of_scope_rejection_rate": (
            sum(1 for m in oos_applicable if m.out_of_scope_correct) / len(oos_applicable)
            if oos_applicable else None
        ),
        "avg_latency_ms": sum(m.latency_ms for m in metrics) / n,
    }
