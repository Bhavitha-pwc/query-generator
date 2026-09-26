"""Single source of truth for paths and environment configuration.

Every other module (nl2sql/, codegen/, dashboard/) imports paths and env-derived
settings from here instead of recomputing `Path(__file__).parent...` or reading
`os.environ` directly. Loads `.env` once, on import.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
SCHEMA_PATH = DATA_DIR / "schema.sql"
SYNTHETIC_DB_PATH = DATA_DIR / "synthetic.db"
TELEMETRY_DB_PATH = DATA_DIR / "telemetry.db"
CODEGEN_TELEMETRY_DB_PATH = DATA_DIR / "codegen_telemetry.db"
GOLD_PATH = DATA_DIR / "gold_queries.json"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_ENHANCER_MODEL = os.environ.get("GROQ_ENHANCER_MODEL", "openai/gpt-oss-20b")
CODEGEN_MODEL = os.environ.get("CODEGEN_MODEL", GROQ_MODEL)


def require_api_key() -> str:
    """Return GROQ_API_KEY or raise with the same actionable message callers expect."""
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Create a .env file with GROQ_API_KEY=... "
            "(copy .env.example) before running generation."
        )
    return GROQ_API_KEY
