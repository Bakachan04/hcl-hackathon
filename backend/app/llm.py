import logging
import os
import time
from typing import Any, Dict, Tuple

import httpx

try:
    from app import config
except ImportError:
    from . import config

logger = logging.getLogger(__name__)

FALLBACK_TEMPLATE = (
    "Production schedule replanned to resolve disruptions. Jobs have been reassigned "
    "to eligible machines within operator shifts and skill levels. All precedence and "
    "capacity constraints are respected."
)


def complete(system: str, user: str) -> Tuple[str, Dict[str, Any]]:
    """Complete a prompt using the configured LLM provider (mock or gemini).

    Agreed contract:
        llm.complete(system, user) -> (text, usage_metadata)
    """
    provider = getattr(config, "LLM_PROVIDER", "mock").lower()
    mock_mode = getattr(config, "MOCK_LLM", False)
    model = getattr(config, "LLM_MODEL", "gemini-3.5-flash-lite")
    api_key = getattr(config, "GEMINI_API_KEY", "")

    # 1. Mock Mode (zero network calls, no API key needed)
    if mock_mode or provider == "mock":
        return FALLBACK_TEMPLATE, {
            "llm_calls": 0,
            "tokens": 0,
            "provider": "mock",
            "fallback": False,
        }

    # 2. Gemini via httpx
    if provider == "gemini":
        if not api_key:
            logger.warning("GEMINI_API_KEY is not set. Using safe fallback template.")
            return FALLBACK_TEMPLATE, {
                "llm_calls": 0,
                "tokens": 0,
                "provider": "gemini",
                "fallback": True,
            }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2},
        }

        max_attempts = 2  # initial attempt + at most 1 retry
        for attempt in range(max_attempts):
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(
                        url,
                        params={"key": api_key},
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )

                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            usage = data.get("usageMetadata", {})
                            tokens = usage.get("totalTokenCount", 0)
                            return text, {
                                "llm_calls": attempt + 1,
                                "tokens": tokens,
                                "provider": "gemini",
                                "fallback": False,
                            }
                logger.warning(
                    "Gemini API returned status %s on attempt %s",
                    response.status_code,
                    attempt + 1,
                )
            except Exception as e:
                # Do not log or leak api_key or full url with query params
                logger.warning(
                    "Gemini API request failed on attempt %s: %s",
                    attempt + 1,
                    type(e).__name__,
                )

            if attempt < max_attempts - 1:
                time.sleep(1.0)

        # Provider failed after 1 retry, return safe fallback template
        return FALLBACK_TEMPLATE, {
            "llm_calls": max_attempts,
            "tokens": 0,
            "provider": "gemini",
            "fallback": True,
        }

    # Default fallback for unknown provider
    return FALLBACK_TEMPLATE, {
        "llm_calls": 0,
        "tokens": 0,
        "provider": provider,
        "fallback": True,
    }

