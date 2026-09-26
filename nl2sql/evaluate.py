"""Wires generation -> gold lookup -> metrics for one question or a full suite."""
import json

from common.config import GOLD_PATH
from nl2sql.generate import generate_sql
from nl2sql.metrics import QueryMetrics, aggregate, evaluate_single
from nl2sql.telemetry import log_trace


def load_gold() -> list[dict]:
    return json.loads(GOLD_PATH.read_text())


def find_gold(question: str, gold_set: list[dict]) -> dict | None:
    normalized = question.strip().lower()
    for entry in gold_set:
        if entry["question"].strip().lower() == normalized:
            return entry
    return None


def evaluate_question(question: str, gold_set: list[dict] | None = None,
                       source: str = "interactive") -> QueryMetrics:
    """Generate SQL for one question and score it against a gold entry if one
    matches verbatim; otherwise returns an ungraded (status/valid_sql only) result.
    Every call is persisted as a trace (see nl2sql/telemetry.py) regardless of
    outcome, tagged by `source` so interactive vs. gold-suite runs are distinguishable.
    """
    if gold_set is None:
        gold_set = load_gold()

    result = generate_sql(question)
    gold_entry = find_gold(question, gold_set)

    metrics = evaluate_single(
        question=question,
        generated_sql=result.sql,
        status=result.status,
        latency_ms=result.latency_ms,
        gold_sql=gold_entry.get("gold_sql") if gold_entry else None,
        expected=gold_entry.get("expected") if gold_entry else None,
        reason=result.reason if result.status == "out_of_scope" else None,
        error=result.reason if result.status == "error" else None,
        explanation=result.explanation,
        tables_used=result.tables_used,
        confidence=result.confidence,
        enhanced_question=result.enhanced_question,
        prompt_enhanced=result.prompt_enhanced,
        enhance_reason=result.enhance_reason,
        enhance_latency_ms=result.enhance_latency_ms,
    )
    metrics.trace_id = log_trace(metrics, source=source)
    return metrics


def run_suite() -> list[QueryMetrics]:
    """Run every fixture in gold_queries.json and return per-query metrics."""
    gold_set = load_gold()
    return [evaluate_question(entry["question"], gold_set, source="suite") for entry in gold_set]


if __name__ == "__main__":
    results = run_suite()
    for r in results:
        print(r.question, "->", r.status, "EX=", r.execution_accuracy)
    print(json.dumps(aggregate(results), indent=2))
