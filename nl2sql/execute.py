"""Read-only execution of generated SQL against the synthetic SQLite dataset."""
import logging
import re
import sqlite3
from dataclasses import dataclass

from common.config import SYNTHETIC_DB_PATH as DB_PATH

logger = logging.getLogger("nl2sql.execute")

_WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|PRAGMA)\b",
    re.IGNORECASE,
)


@dataclass
class ExecutionResult:
    ok: bool
    columns: list[str]
    rows: list[tuple]
    error: str | None


def is_read_only(sql: str) -> bool:
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    if len(statements) != 1:
        return False
    if not statements[0].lstrip().upper().startswith("SELECT"):
        return False
    return not _WRITE_KEYWORDS.search(statements[0])


def run_query(sql: str) -> ExecutionResult:
    if not is_read_only(sql):
        return ExecutionResult(False, [], [], "Refused: only a single read-only SELECT is allowed.")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA query_only = ON;")
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        conn.close()
        return ExecutionResult(True, columns, rows, None)
    except sqlite3.Error as exc:
        logger.warning("query execution failed: %s | sql=%.200s", exc, sql)
        return ExecutionResult(False, [], [], str(exc))
