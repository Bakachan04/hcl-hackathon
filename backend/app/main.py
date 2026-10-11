"""FastAPI app: the API contract from guide section 6."""

from fastapi import FastAPI, HTTPException

from app import config, graph, store
from app.routes_ingest import router as ingest_router
from app.schemas import AnalyzeRequest, AnalyzeResponse

app = FastAPI(title="Production Re-Planner API")
app.include_router(ingest_router)


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


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    return graph.run(req)


@app.get("/trace/{run_id}")
def trace(run_id: str):
    record = store.get_trace(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No trace for run {run_id}")
    return record
