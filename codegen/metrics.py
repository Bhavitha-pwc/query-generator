"""Evaluation metrics for one generated program.

Unlike nl2sql's metrics (which compare against a gold SQL query), there's no
gold reference for an arbitrary code-generation task, so these are all metrics
computable from the generated code alone:
- Syntax validity (language's compiler/parser front-end; None if no local
  toolchain is available for that language — reported honestly, not guessed).
- Lint issue count via pyflakes, Python only for now.
- Compiler warning count for C/C++/Java (from -Wall / -Xlint:all on a
  successful compile; None if the language has no compiler warnings concept
  or the compile itself failed).
- Size (lines of code, characters) and an approximate token count.
- Latency, carried over from generation.
"""
import io
from contextlib import redirect_stdout
from dataclasses import dataclass

from codegen.languages import SUPPORTED_LANGUAGES


@dataclass
class CodeMetrics:
    language: str
    syntax_checker_available: bool
    syntax_valid: bool | None
    syntax_error: str | None
    lint_issue_count: int | None   # Python only (pyflakes); None elsewhere
    warning_count: int | None      # C/C++/Java compiler warnings; None elsewhere or on failed compile
    lines_of_code: int
    char_count: int
    approx_token_count: int
    latency_ms: float


def _pyflakes_issue_count(code: str) -> int:
    from pyflakes.api import check
    from pyflakes.reporter import Reporter

    out = io.StringIO()
    with redirect_stdout(out):
        issue_count = check(code, "<generated>", Reporter(out, out))
    return issue_count


def evaluate_code(language: str, code: str, latency_ms: float) -> CodeMetrics:
    lang = SUPPORTED_LANGUAGES[language]
    check_result = lang.checker(code)

    lint_issue_count = None
    if lang.supports_lint and check_result.valid:
        lint_issue_count = _pyflakes_issue_count(code)

    lines = code.splitlines()
    return CodeMetrics(
        language=language,
        syntax_checker_available=check_result.available,
        syntax_valid=check_result.valid,
        syntax_error=check_result.error,
        lint_issue_count=lint_issue_count,
        warning_count=check_result.warning_count,
        lines_of_code=len(lines),
        char_count=len(code),
        approx_token_count=len(code.split()),
        latency_ms=latency_ms,
    )
