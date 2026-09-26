"""English question -> SQL, or an explicit OUT_OF_SCOPE refusal.

Two model calls happen per question, and both report *why* they did what they
did — this is the traceability trail the dashboard renders step by step:
1. A prompt-enhancer pass that fixes typos/grammar/ambiguity in the user's raw
   question without changing its intent or scope, and states what it changed
   and why (falls back to the original question on any failure — it never
   blocks generation).
2. The actual NL->SQL generation call, which reports which tables it grounded
   the query on, its confidence, and a short rationale for the columns/joins/
   filters it picked.

Calls Groq's chat completion API (OpenAI-compatible) via common.llm_client.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache

from common.config import GROQ_ENHANCER_MODEL, GROQ_MODEL, SCHEMA_PATH
from common.llm_client import chat_json

logger = logging.getLogger("nl2sql.generate")

GENERATION_MODEL = GROQ_MODEL
ENHANCER_MODEL = GROQ_ENHANCER_MODEL

ENHANCER_SYSTEM_PROMPT = """You clean up English questions that will be turned into a SQL \
query against this schema:

{schema}

Rewrite the user's question ONLY if it has typos, grammar problems, or is ambiguous/vague — \
fix those while preserving the original intent exactly. Do not add filters, columns, or \
requirements the user didn't ask for. Do not try to answer or reword questions that are \
already unrelated to this schema — leave those verbatim.

Respond with ONLY a single JSON object, no markdown fences, no extra text:
{{"question": "<possibly rewritten question>", "changed": true or false, \
"reason": "<one short sentence on what you changed and why, or \\"already clear\\" if unchanged>"}}
"""

SYSTEM_PROMPT_TEMPLATE = """You translate English questions into a single SQLite SELECT \
query, using ONLY the following schema:

{schema}

Rules:
- You may only reference tables and columns that appear in the schema above.
- Only ever produce a single read-only SELECT statement. Never produce INSERT, \
UPDATE, DELETE, DROP, ALTER, or multiple statements.
- If the question cannot be answered using only this schema (it needs data or a \
column that doesn't exist here, or isn't a database question at all), do not guess.
- Respond with ONLY a single JSON object, no markdown fences, no extra text:
  - If answerable: {{"sql": "<SELECT statement>", "tables_used": ["<table1>", "<table2>"], \
"explanation": "<1-2 sentences on why you chose these tables/columns/joins/filters>", \
"confidence": "high" | "medium" | "low"}}
  - If not answerable: {{"status": "out_of_scope", "reason": "<short reason>"}}
"""


@dataclass
class GenerationResult:
    question: str             # original, exactly as typed by the user
    enhanced_question: str    # after the prompt-enhancer pass (== question if unchanged)
    prompt_enhanced: bool
    enhance_reason: str | None  # why the enhancer changed it (or "already clear")
    status: str                # "ok" | "out_of_scope" | "error"
    sql: str | None
    tables_used: list[str] = field(default_factory=list)
    explanation: str | None = None   # model's stated rationale for the query it wrote
    confidence: str | None = None     # "high" | "medium" | "low", self-reported
    reason: str | None = None         # refusal / error reason
    latency_ms: float = 0.0           # total (enhancer + generation)
    enhance_latency_ms: float = 0.0


@lru_cache(maxsize=1)
def _load_schema() -> str:
    # Schema is static for the process lifetime — cached to avoid a disk read
    # (and re-formatting into two prompts) on every question.
    return SCHEMA_PATH.read_text()


def _extract_sql(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return text.rstrip(";").strip() + ";"


def _enhance(question: str, schema: str, model: str = ENHANCER_MODEL) -> tuple[str, bool, str, float]:
    """Best-effort rewrite of a rough/ambiguous question. Never raises — falls
    back to the original question, unchanged, on any error so it can't block
    generation. Returns (question, changed, reason, latency_ms).
    """
    start = time.perf_counter()
    try:
        parsed, _raw, call_latency_ms = chat_json(
            ENHANCER_SYSTEM_PROMPT.format(schema=schema), question, model, max_tokens=250,
        )
        rewritten = (parsed.get("question") or question).strip()
        changed = bool(parsed.get("changed")) and rewritten != question.strip()
        reason = parsed.get("reason") or ("already clear" if not changed else "rewritten")
    except Exception as exc:
        logger.warning("prompt enhancer unavailable, using original question: %s", exc)
        rewritten, changed, reason = question, False, f"enhancer unavailable: {exc}"
    latency_ms = (time.perf_counter() - start) * 1000
    return rewritten, changed, reason, latency_ms


def generate_sql(question: str, model: str = GENERATION_MODEL, enhance: bool = True) -> GenerationResult:
    schema = _load_schema()

    enhanced_question, prompt_enhanced, enhance_reason, enhance_latency_ms = question, False, None, 0.0
    if enhance:
        enhanced_question, prompt_enhanced, enhance_reason, enhance_latency_ms = _enhance(question, schema)

    common = dict(
        question=question,
        enhanced_question=enhanced_question,
        prompt_enhanced=prompt_enhanced,
        enhance_reason=enhance_reason,
        enhance_latency_ms=enhance_latency_ms,
    )

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)
    start = time.perf_counter()
    try:
        parsed, raw, gen_latency_ms = chat_json(system_prompt, enhanced_question, model, max_tokens=500)
    except Exception as exc:  # network/auth/model errors surface to the dashboard
        gen_latency_ms = (time.perf_counter() - start) * 1000
        logger.error("generation call failed for question=%r: %s", question, exc)
        return GenerationResult(
            **common, status="error", sql=None, reason=str(exc),
            latency_ms=enhance_latency_ms + gen_latency_ms,
        )

    total_latency_ms = enhance_latency_ms + gen_latency_ms

    if parsed.get("status") == "out_of_scope":
        return GenerationResult(
            **common, status="out_of_scope", sql=None,
            reason=parsed.get("reason", "not answerable from schema"),
            latency_ms=total_latency_ms,
        )

    if "sql" not in parsed:
        # nothing usable parsed out of the response at all
        logger.warning("could not parse model response for question=%r: %.200s", question, raw)
        return GenerationResult(
            **common, status="error", sql=None,
            reason=f"could not parse model response: {raw[:200]}",
            latency_ms=total_latency_ms,
        )

    sql = _extract_sql(parsed["sql"])
    return GenerationResult(
        **common, status="ok", sql=sql,
        tables_used=parsed.get("tables_used") or [],
        explanation=parsed.get("explanation"),
        confidence=parsed.get("confidence"),
        reason=None,
        latency_ms=total_latency_ms,
    )


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "List all customers from Austin."
    result = generate_sql(q)
    print(json.dumps(result.__dict__, indent=2))
