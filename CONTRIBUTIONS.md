# Team contribution statement

Team: Adarsh, Lavanya, Ridhi. Each person worked on their own branch (`Adarsh`, `Lavanya`, `Ridhi`) and merged to `main` through pull requests; the Git history shows who wrote what.

| Member | Built | Key files |
|---|---|---|
| **Adarsh** | Project setup and shared data contract; CP-SAT solver (machines, changeovers, operators, shifts, overtime, fixed WIP); greedy start/fallback plan; re-planning (breakdowns, rush orders, stability); plan diff with reasons; LangGraph pipeline; `/analyze`, `/trace`, `/health`; sample traces | `backend/app/solver.py`, `diff.py`, `graph.py`, `main.py`, `schemas.py`, `config.py`, `tests/test_solver.py`, `tests/test_analyze.py` |
| **Lavanya** | Synthetic data generator with planted edge cases and data card; CSV loader and validation script; SQLite store; `/ingest`; Dockerfile and docker compose; evaluation set, runner and report | `backend/scripts/*`, `backend/app/loader.py`, `validation.py`, `store.py`, `routes_ingest.py`, `backend/eval/*`, `docs/data_card.md`, `Dockerfile`, `docker-compose.yml` |
| **Ridhi** | Independent plan checker and KPI calculation; LLM wrapper (Gemini / mock); plain-language explanation with fact checking; Streamlit UI with Gantt chart; README | `backend/app/checker.py`, `llm.py`, `explain.py`, `ui/streamlit_app.py`, `README.md` |

_Each member: check your row and correct anything missing before the freeze._
