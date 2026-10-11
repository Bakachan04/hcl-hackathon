# Production Re-Planner Under Disruption

HCLTech Future Ready AI Engineer Hackathon. A system that builds a valid production schedule with a solver (OR-Tools CP-SAT), re-plans when a machine breaks down or a rush order arrives, checks every plan against the scheduling rules, and has an LLM explain what changed using only facts returned by the tools.

> **Status:** working end to end: data generation and validation, CP-SAT planning and re-planning, plan checker, explanations, API, UI.

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

## Architecture

```
Streamlit UI ──HTTP──► FastAPI  (/analyze  /ingest  /health  /trace/{run_id})
                           │
                           ▼
        LangGraph pipeline (fixed steps, every step recorded in the trace)
  parse_request ─► solve_schedule ─► validate_plan ─► diff_plans ─► explain
   (keyword       (CP-SAT tool,      (our checker:    (what moved,   (LLM rephrases
    routing)       greedy start)      every rule)      reason codes)  tool facts only)
        │
        └─► refused / clarification_needed answered directly, no solver call
                           │
                           ▼
                SQLite: data tables, plans, traces
```

- **The solver builds every plan; the LLM never writes or edits one.** CP-SAT models machine choice, capacity, step order, direction-dependent changeovers, operator skill, shifts and overtime. A greedy earliest-due-date plan gives it a valid starting point and is the fallback if it times out.
- **A plan is only returned if our own checker passes every rule** (capacity, eligibility, changeover, precedence, skill, shift, WIP, breakdown).
- **Reasons for every change are computed in code** (`diff_plans`); the explanation starts with a headline built from tool results, and LLM text is fact-checked against those results.
- **Why one pipeline, not several agents:** routing, solving and checking are deterministic; only the explanation needs language. More agents would add failure modes without meeting any extra requirement.

## API examples

```powershell
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" -d "{\"request\": \"Build today's schedule.\"}"
curl -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" -d "{\"request\": \"Machine CNC-3 is down for 6 hours from 10:00. Re-plan.\"}"
curl -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" -d "{\"request\": \"Why did order O-107 move?\"}"
curl -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" -d "{\"request\": \"Re-plan\", \"disruption\": [{\"event_id\": \"E1\", \"kind\": \"breakdown\", \"at\": \"2026-10-12T10:00:00\", \"target\": \"CNC-3\", \"duration_h\": 6}], \"weights\": {\"late\": 10, \"overtime\": 3, \"changeover\": 1}}"
curl http://127.0.0.1:8000/trace/<run_id>
```

Sample traces for three answer types: [docs/sample_traces/](docs/sample_traces/).

## Assumptions

- Shifts: A 06:00–14:00, B 14:00–22:00, every day; up to 2 h overtime after shift end.
- A job must start inside the regular shift; overtime only finishes a running job. Jobs never split.
- Skill levels L1 < L2 < L3; a higher level can do lower-level work.
- Weights: `late` = cost per hour late (× priority factor: P1 ×3, P2 ×2, P3 ×1; key customers ×2), `overtime` = per hour, `changeover` = per changeover. Defaults 10 / 3 / 1, changeable per request.
- On a replan, work started before the disruption stays; a job running on the broken machine restarts from scratch. Moving a job away from the old plan costs 1 per hour moved and per machine change.
- Solver time limit 10 s (`SOLVER_TIME_LIMIT_S`).

## Limitations and known edge cases

- CP-SAT rarely proves optimality within 10 s on 45+ orders; plans are valid but may not be the best possible. Quality drops as the data grows (measured at 60 and 90 orders).
- Re-plans are stable where possible, but a long breakdown on a bottleneck machine moves many downstream jobs.
- Requests are routed by keyword rules; unusual phrasing may get `clarification_needed`. Explicit deadline requests ("finish all by 17:00", answer type `infeasible`) and the with/without-overtime trade-off answer are not implemented yet; `avoid_overtime: true` in the request plans without overtime.
- "Why did order X move?" uses the most recent replan held in memory; it is lost when the API restarts.
- Edge cases from the data pack (where they are planted is in [docs/data_card.md](docs/data_card.md)): order only runnable on the broken machine, rare-skill operator, direction-dependent changeovers, rush order with the same due date as a P1 order, unmovable WIP, a disruption that makes on-time delivery impossible.
