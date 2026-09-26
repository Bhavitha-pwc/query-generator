"""Status label/color mapping for a QueryMetrics result — shared by the query,
eval, and history panels so all three agree on what "Pass"/"Fail"/etc. mean.
"""
from nl2sql.metrics import QueryMetrics

from dashboard.theme import COLOR_CRITICAL, COLOR_GOOD, COLOR_MUTED


def status_label(m: QueryMetrics) -> str:
    if m.status == "error":
        return "Error"
    if m.status == "out_of_scope":
        if m.out_of_scope_correct is True:
            return "Correctly refused"
        if m.out_of_scope_correct is False:
            return "Incorrectly refused"
        return "Refused (ungraded)"
    if m.execution_accuracy is True:
        return "Pass"
    if m.execution_accuracy is False:
        return "Fail"
    return "Ungraded" if m.valid_sql else "Invalid SQL"


def status_color(label: str) -> str:
    if label in ("Pass", "Correctly refused"):
        return COLOR_GOOD
    if label in ("Fail", "Error", "Invalid SQL", "Incorrectly refused"):
        return COLOR_CRITICAL
    return COLOR_MUTED
