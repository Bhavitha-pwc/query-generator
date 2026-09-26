"""Shared Groq chat-completion helper: build a client once, send a system+user
prompt pair, and parse the JSON object out of the response. Used by both
nl2sql/generate.py (English -> SQL) and codegen/generate.py (task -> source code)
so the request/parse/timing logic exists in exactly one place.
"""
import json
import logging
import re
import time
from functools import lru_cache

from groq import Groq

from common.config import require_api_key

logger = logging.getLogger("common.llm_client")


@lru_cache(maxsize=1)
def get_client() -> Groq:
    return Groq(api_key=require_api_key())


def parse_json_response(raw: str) -> dict:
    """Parse a model response as JSON, tolerating markdown fences or stray text
    around the JSON object. Returns {} if nothing parses.
    """
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def chat_text(system_prompt: str, user_content: str, model: str,
              max_tokens: int = 500, temperature: float = 0) -> tuple[str, float]:
    """Send one system+user turn, return (raw_text, latency_ms). Raises whatever
    the Groq SDK raises on network/auth/model errors — callers decide how to
    report that (fall back silently vs. surface it), so this stays a thin,
    error-transparent wrapper.
    """
    start = time.perf_counter()
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    return response.choices[0].message.content.strip(), latency_ms


def chat_json(system_prompt: str, user_content: str, model: str,
              max_tokens: int = 500, temperature: float = 0) -> tuple[dict, str, float]:
    """Like chat_text, but also parses the response as a JSON object. Only safe
    for prompts whose payload doesn't itself contain multi-line text with quotes/
    backslashes (e.g. single-line SQL) — models reliably double-escape embedded
    newlines otherwise. codegen/generate.py uses chat_text with a plain delimited
    format instead, precisely to avoid that failure mode for multi-line source code.
    """
    raw, latency_ms = chat_text(system_prompt, user_content, model, max_tokens, temperature)
    return parse_json_response(raw), raw, latency_ms
