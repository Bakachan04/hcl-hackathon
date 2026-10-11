# Production Re-Planner Under Disruption

HCLTech Future Ready AI Engineer Hackathon. A system that builds a valid production schedule with a solver (OR-Tools CP-SAT), re-plans when a machine breaks down or a rush order arrives, checks every plan against the scheduling rules, and has an LLM explain what changed using only facts returned by the tools.

> **Status:** work in progress. Project layout, shared data models and `GET /health` are in place. Solver, checker, loader and UI are being built.

## Tech stack

| Layer | Choice |
|---|---|
| UI | Streamlit, Plotly (Gantt chart) |
| API | FastAPI, Uvicorn, Pydantic v2 |
| Orchestration | LangGraph |
| Solver | OR-Tools CP-SAT |
| Data | pandas, SQLite |
| LLM | Google Gemini (`gemini-3.5-flash-lite`) via `LLM_PROVIDER` / `LLM_MODEL`; `MOCK_LLM=true` runs without a key |
| Quality | pytest, ruff |

## Project structure

```
backend/
  app/            FastAPI app, schemas, solver, checker, loader, LLM, pipeline
  scripts/        data generator, CLI loader, validation script
  eval/           evaluation set and runner
  tests/
ui/               Streamlit app
docs/             data card, AI-usage disclosure, sample traces
data/raw/         generated CSVs (not in Git)
```

## Setup (Python 3.11)

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env     # then edit .env (keys never go in Git)
```

## Data

```powershell
# from backend/
.\.venv\Scripts\python.exe scripts\generate_data.py --seed 42 --out ..\data\raw   # synthetic pack (same seed = same files)
.\.venv\Scripts\python.exe scripts\load_data.py ..\data\raw                       # load any Annex B folder into SQLite
.\.venv\Scripts\python.exe scripts\validate_data.py                               # PASS/FAIL table (guide 4.5)
```

Load one table while the API is running:

```powershell
curl -F "file=@data/raw/orders.csv" -F "meta={\"table\":\"orders\"}" http://localhost:8000/ingest
```

What the data contains and where each edge case is planted: [docs/data_card.md](docs/data_card.md).

## Docker

```powershell
docker compose up --build    # API on :8000 (generates + loads data on first start), UI on :8501
```

## Run

```powershell
# from backend/
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
curl http://127.0.0.1:8000/health
```

## Test

```powershell
# from backend/
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```
