"""Registry of languages the code generator can target, each with a compile- or
parse-only syntax checker. Checkers never execute the generated program — only a
parser/compiler front-end (`--check`, `-fsyntax-only`, `compile()`, `EXPLAIN`) —
so running arbitrary model output stays safe.
"""
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from codegen import runner

_TIMEOUT_S = 10


@dataclass
class SyntaxCheckResult:
    available: bool          # whether a local toolchain could even run this check
    valid: bool | None        # None when unavailable
    error: str | None = None
    warning_count: int | None = None   # compiler warnings on a *successful* compile; None if n/a


_WARNING_RE = re.compile(r"\bwarning:", re.IGNORECASE)


def _count_warnings(text: str) -> int:
    return len(_WARNING_RE.findall(text))


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
        return proc.returncode == 0, (proc.stderr or proc.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "syntax check timed out"


def check_python(code: str) -> SyntaxCheckResult:
    try:
        compile(code, "<generated>", "exec")
        return SyntaxCheckResult(True, True)
    except SyntaxError as exc:
        return SyntaxCheckResult(True, False, str(exc))


def check_javascript(code: str) -> SyntaxCheckResult:
    if not shutil.which("node"):
        return SyntaxCheckResult(False, None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "generated.js"
        path.write_text(code)
        ok, msg = _run(["node", "--check", str(path)])
        return SyntaxCheckResult(True, ok, None if ok else msg)


def check_java(code: str) -> SyntaxCheckResult:
    if not shutil.which("javac"):
        return SyntaxCheckResult(False, None)
    match = re.search(r"public\s+class\s+(\w+)", code)
    if not match:
        return SyntaxCheckResult(False, None, "no public class found to compile")
    class_name = match.group(1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{class_name}.java"
        path.write_text(code)
        ok, msg = _run(["javac", "-Xlint:all", "-d", tmp, str(path)])
        return SyntaxCheckResult(True, ok, None if ok else msg, _count_warnings(msg) if ok else None)


def _check_c_family(code: str, compiler: str, extra_flags: list[str], suffix: str) -> SyntaxCheckResult:
    if not shutil.which(compiler):
        return SyntaxCheckResult(False, None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"generated{suffix}"
        path.write_text(code)
        ok, msg = _run([compiler, "-fsyntax-only", *extra_flags, str(path)])
        return SyntaxCheckResult(True, ok, None if ok else msg, _count_warnings(msg) if ok else None)


def check_cpp(code: str) -> SyntaxCheckResult:
    return _check_c_family(code, "g++", ["-std=c++17", "-Wall"], ".cpp")


def check_c(code: str) -> SyntaxCheckResult:
    return _check_c_family(code, "gcc", ["-Wall"], ".c")


def check_sql(code: str) -> SyntaxCheckResult:
    """Structural check only — runs EXPLAIN against an empty in-memory DB, so
    "no such table/column" (semantics we can't know without a schema) doesn't
    count as a syntax error, but real SQL syntax errors still do.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(f"EXPLAIN {code.rstrip(';')}")
        return SyntaxCheckResult(True, True)
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such table" in message or "no such column" in message:
            return SyntaxCheckResult(True, True)
        return SyntaxCheckResult(True, False, str(exc))
    finally:
        conn.close()


@dataclass
class Language:
    key: str              # value stored/sent to the LLM prompt
    display_name: str
    streamlit_lexer: str  # language name st.code() understands
    checker: callable      # str -> SyntaxCheckResult
    runner: callable        # (code, stdin_text) -> runner.RunResult
    supports_lint: bool = False   # pyflakes is Python-only for now
    accepts_stdin: bool = True    # SQL has no stdin concept


SUPPORTED_LANGUAGES: dict[str, Language] = {
    lang.key: lang for lang in [
        Language("python", "Python", "python", check_python, runner.run_python, supports_lint=True),
        Language("javascript", "JavaScript", "javascript", check_javascript, runner.run_javascript),
        Language("java", "Java", "java", check_java, runner.run_java),
        Language("cpp", "C++", "cpp", check_cpp, runner.run_cpp),
        Language("c", "C", "c", check_c, runner.run_c),
        Language("sql", "SQL", "sql", check_sql, runner.run_sql, accepts_stdin=False),
    ]
}
