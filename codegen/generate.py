"""Task description -> generated source code in a user-chosen language.

Uses a plain delimited text protocol (STATUS/EXPLANATION/CODE), not JSON —
asking a model to JSON-encode multi-line source code (embedded newlines,
quotes, backslashes, braces) is a known failure mode: models reliably
double-escape newlines, corrupting the code. nl2sql/generate.py's SQL is
single-line so JSON works fine there; this doesn't, so it doesn't use it.

One model call, no prompt-enhancer pass (unlike nl2sql/generate.py) — a code
generation prompt doesn't need the same typo/ambiguity cleanup step the SQL
flow relies on for schema grounding.
"""
import logging
import re
from dataclasses import dataclass

from common.config import CODEGEN_MODEL
from common.llm_client import chat_text
from codegen.languages import SUPPORTED_LANGUAGES

logger = logging.getLogger("codegen.generate")

SYSTEM_PROMPT_TEMPLATE = """You write a single, complete, runnable {language} program that \
accomplishes the user's task.

Respond in EXACTLY this format and nothing else — no markdown fences around the whole \
response, no extra commentary before or after:

STATUS: ok
EXPLANATION: <one sentence on your approach>
CODE:
<the complete {language} program, as real unescaped code, to the end of your response>

If the task needs any input values, read them from standard input (stdin) — do not \
hardcode example values or rely on command-line arguments.

If the task is not actually a programming task (e.g. a general-knowledge question with \
nothing to write code for), respond in EXACTLY this format instead:

STATUS: out_of_scope
REASON: <short reason>
"""

_CODE_MARKER = re.compile(r"^CODE:\s*\n?", re.MULTILINE)
_FENCE = re.compile(r"^```[a-zA-Z0-9+#-]*\s*\n?(.*?)\n?```$", re.DOTALL)


@dataclass
class CodeGenResult:
    task: str
    language: str
    status: str            # "ok" | "out_of_scope" | "error"
    code: str | None = None
    explanation: str | None = None
    reason: str | None = None
    latency_ms: float = 0.0


def _parse_response(raw: str) -> dict:
    """Best-effort parse of the STATUS/EXPLANATION/CODE (or REASON) format."""
    lines = raw.strip().splitlines()
    fields: dict[str, str] = {}
    for i, line in enumerate(lines):
        if line.upper().startswith("STATUS:"):
            fields["status"] = line.split(":", 1)[1].strip().lower()
        elif line.upper().startswith("EXPLANATION:"):
            fields["explanation"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("REASON:"):
            fields["reason"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("CODE:"):
            code = "\n".join(lines[i:])
            code = _CODE_MARKER.sub("", code, count=1)
            fenced = _FENCE.match(code.strip())
            fields["code"] = fenced.group(1) if fenced else code.strip()
            break
    return fields


def generate_code(task: str, language: str, model: str = CODEGEN_MODEL) -> CodeGenResult:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language!r}")

    display_name = SUPPORTED_LANGUAGES[language].display_name
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(language=display_name)

    try:
        raw, latency_ms = chat_text(system_prompt, task, model, max_tokens=1500)
    except Exception as exc:  # network/auth/model errors surface to the dashboard
        logger.error("code generation call failed for task=%r (%s): %s", task, language, exc)
        return CodeGenResult(task=task, language=language, status="error", reason=str(exc))

    parsed = _parse_response(raw)

    if parsed.get("status") == "out_of_scope":
        return CodeGenResult(
            task=task, language=language, status="out_of_scope",
            reason=parsed.get("reason", "not a code generation task"), latency_ms=latency_ms,
        )

    if not parsed.get("code"):
        logger.warning("could not parse model response for task=%r: %.200s", task, raw)
        return CodeGenResult(
            task=task, language=language, status="error",
            reason=f"could not parse model response: {raw[:200]}", latency_ms=latency_ms,
        )

    return CodeGenResult(
        task=task, language=language, status="ok",
        code=parsed["code"],
        explanation=parsed.get("explanation"),
        latency_ms=latency_ms,
    )


if __name__ == "__main__":
    import argparse
    import json

    from codegen.metrics import evaluate_code

    parser = argparse.ArgumentParser(description="Generate code for a task from the CLI.")
    parser.add_argument("task", nargs="+", help="Task description, e.g. 'reverse a string'")
    parser.add_argument(
        "--lang", "--language", dest="language", default="python",
        choices=sorted(SUPPORTED_LANGUAGES), help="Target language (default: python)",
    )
    args = parser.parse_args()

    result = generate_code(" ".join(args.task), args.language)
    print(json.dumps(result.__dict__, indent=2))

    if result.status == "ok" and result.code:
        metrics = evaluate_code(result.language, result.code, result.latency_ms)
        print(json.dumps(metrics.__dict__, indent=2))
