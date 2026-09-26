"""Executes a generated program locally, with stdin passthrough, and returns
its stdout/stderr/exit code.

Unlike codegen/languages.py's syntax checkers (compile/parse-only, never
execute), this module *does* run the generated code — the whole point of the
"Run" button is to execute code the user just reviewed on their own machine,
the same way a "Run" button in an IDE would. Safety measures kept in place:
a hard wall-clock timeout, isolated temp directories per run, no shell=True /
string interpolation into a shell, and no execution happens anywhere except
here in response to an explicit user click.
"""
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_RUN_TIMEOUT_S = 10


@dataclass
class RunResult:
    available: bool            # False if no local toolchain to run this language
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    error: str | None = None   # set when available=False, or a step (e.g. compile) failed


def _exec(cmd: list[str], stdin_text: str, cwd: str | None = None) -> RunResult:
    try:
        proc = subprocess.run(
            cmd, input=stdin_text, capture_output=True, text=True,
            timeout=_RUN_TIMEOUT_S, cwd=cwd,
        )
        return RunResult(True, proc.stdout, proc.stderr, proc.returncode)
    except subprocess.TimeoutExpired:
        return RunResult(True, timed_out=True, error=f"execution timed out after {_RUN_TIMEOUT_S}s")


def run_python(code: str, stdin_text: str = "") -> RunResult:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "generated.py"
        path.write_text(code)
        return _exec(["python3", str(path)], stdin_text)


def run_javascript(code: str, stdin_text: str = "") -> RunResult:
    if not shutil.which("node"):
        return RunResult(False, error="node is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "generated.js"
        path.write_text(code)
        return _exec(["node", str(path)], stdin_text)


def run_java(code: str, stdin_text: str = "") -> RunResult:
    if not shutil.which("javac") or not shutil.which("java"):
        return RunResult(False, error="javac/java is not installed")
    match = re.search(r"public\s+class\s+(\w+)", code)
    if not match:
        return RunResult(True, error="no public class found to compile")
    class_name = match.group(1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{class_name}.java"
        path.write_text(code)
        compile_proc = subprocess.run(
            ["javac", "-d", tmp, str(path)], capture_output=True, text=True, timeout=_RUN_TIMEOUT_S,
        )
        if compile_proc.returncode != 0:
            return RunResult(True, stderr=compile_proc.stderr, exit_code=compile_proc.returncode,
                              error="compilation failed")
        return _exec(["java", "-cp", tmp, class_name], stdin_text)


def _compile_and_run_c_family(code: str, compiler: str, extra_flags: list[str], suffix: str,
                               stdin_text: str) -> RunResult:
    if not shutil.which(compiler):
        return RunResult(False, error=f"{compiler} is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"generated{suffix}"
        binary = Path(tmp) / "generated.out"
        source.write_text(code)
        compile_proc = subprocess.run(
            [compiler, *extra_flags, str(source), "-o", str(binary)],
            capture_output=True, text=True, timeout=_RUN_TIMEOUT_S,
        )
        if compile_proc.returncode != 0:
            return RunResult(True, stderr=compile_proc.stderr, exit_code=compile_proc.returncode,
                              error="compilation failed")
        return _exec([str(binary)], stdin_text)


def run_cpp(code: str, stdin_text: str = "") -> RunResult:
    return _compile_and_run_c_family(code, "g++", ["-std=c++17"], ".cpp", stdin_text)


def run_c(code: str, stdin_text: str = "") -> RunResult:
    return _compile_and_run_c_family(code, "gcc", [], ".c", stdin_text)


def run_sql(code: str, stdin_text: str = "") -> RunResult:
    """Runs the generated script (possibly multiple statements — CREATE/INSERT/
    SELECT/etc.) against a fresh in-memory SQLite database, isolated per run.
    Any statement that returns rows has its result rendered into stdout, like a
    SQL script runner would. `stdin_text` is unused — SQL has no stdin concept.
    """
    statements = [s.strip() for s in code.split(";") if s.strip()]
    conn = sqlite3.connect(":memory:")
    output_lines = []
    try:
        for stmt in statements:
            cursor = conn.execute(stmt)
            if cursor.description:
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
                output_lines.append(" | ".join(columns))
                output_lines.extend(" | ".join(str(v) for v in row) for row in rows)
        conn.commit()
        return RunResult(True, stdout="\n".join(output_lines), exit_code=0)
    except sqlite3.Error as exc:
        return RunResult(True, stdout="\n".join(output_lines), stderr=str(exc), exit_code=1)
    finally:
        conn.close()
