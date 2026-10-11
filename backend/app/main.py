"""FastAPI app: the API contract from guide section 6."""

from fastapi import FastAPI

from app import config

app = FastAPI(title="Production Re-Planner API")


def _llm_status() -> str:
    if config.MOCK_LLM or config.LLM_PROVIDER == "mock":
        return "mock"
    if config.LLM_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        return "missing_key"
    return "configured"


@app.get("/health")
def health():
    return {
        "api": "ok",
        "data_store": "ok" if config.DB_PATH.exists() else "empty",
        "llm": _llm_status(),
        "llm_provider": config.LLM_PROVIDER,
        "llm_model": config.LLM_MODEL,
    }
