"""All settings in one place, read from backend/.env (see .env.example)."""

import os
from datetime import datetime, time
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


def _path(value: str) -> Path:
    """Relative paths are resolved against backend/, so the cwd doesn't matter."""
    p = Path(value)
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


# LLM switch
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")  # gemini | ollama | mock
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
MOCK_LLM = os.getenv("MOCK_LLM", "true").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Planning
PLAN_START = datetime.strptime(os.getenv("PLAN_START", "2026-10-12 06:00"), "%Y-%m-%d %H:%M")
SOLVER_TIME_LIMIT_S = float(os.getenv("SOLVER_TIME_LIMIT_S", "10"))

# Shift codes -> (start, end). Operators may work up to OVERTIME_MAX_H past shift end.
SHIFTS = {"A": (time(6, 0), time(14, 0)), "B": (time(14, 0), time(22, 0))}
OVERTIME_MAX_H = 2

# Priority 1 lateness hurts most; key customers (tier 1) count double.
PRIORITY_FACTOR = {1: 3, 2: 2, 3: 1}
KEY_CUSTOMER_FACTOR = 2

# Storage
DB_PATH = _path(os.getenv("DB_PATH", "../data/planner.db"))
DATA_DIR = _path(os.getenv("DATA_DIR", "../data/raw"))
