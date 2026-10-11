# Tasks: Lavanya

**Project:** Production Re-Planner Under Disruption (HCLTech hackathon, 11 Oct 2026)
**Code freeze:** 16:15 · **Late data drop:** 13:45 · **Team:** Adarsh, Lavanya, Ridhi

**You own:** the synthetic data pack and its data card, the loader and validation script, the SQLite store, `POST /ingest`, Docker, and the evaluation set and report.
**Requirements covered:** R1, guide §4 (data, validation, loader), §7 (evaluation), §8 packaging.

---

## Dependencies at a glance

| You wait on | For | Until then |
|---|---|---|
| Adarsh: A1 `schemas.py` + folder layout on `main` (~13:05) | Loader output types | Start L1 (Docker) and L2 (generator); neither needs it |
| Adarsh: `main.py` with routers (~14:00) | Plugging `/ingest` into the app | Build `routes_ingest.py` as an `APIRouter` and test it alone |
| Adarsh + Ridhi: `/analyze` running end to end (~15:15) | Running the evaluation | Write `eval/cases.json` first |
| Ridhi: `checker.validate_plan` + `compute_kpis` (~13:45) | Evaluation metrics (validity, KPIs) | — |
| Everyone merged to `main` (~15:30) | Final `docker compose up` test | Test Docker with what exists |

| Others wait on you | What | Needed by |
|---|---|---|
| Adarsh, Ridhi | **L2: generated CSVs in `data/raw/`** (realistic solver and checker tests) | **13:45** |
| Adarsh | L3/L4: `loader.load_problem()` and `store.py` | 14:30 |
| Ridhi | L4: `store.get_trace()` for the UI's trace view | 15:00 |
| Whole team | L6: Docker working on Adarsh's laptop (demo machine) | 15:30 |

---

## Tasks

### L1. Start the Docker install now (12:50, ~5 min hands-on) — on **Adarsh's laptop** (the demo machine)
- [ ] Open PowerShell **as administrator** and run `wsl --install`. Let it download.
- [ ] Reboot during lunch (13:00), so nobody loses build time.
- [ ] After the reboot, install Docker Desktop and run `docker run hello-world`.
- [ ] If anything fails, install on your own laptop as the backup demo machine and tell the team.

### L2. Synthetic data generator + data card (12:55–13:45) — **blocks realistic testing for the team**
- [ ] `backend/scripts/generate_data.py --seed 42 --out data/raw/` writes `orders.csv`, `routings_machines.csv`, `changeovers_skills.csv`, `disruption.csv` in the Annex B schema, plus our optional extra columns (see Shared contracts).
- [ ] **Minimums (guide §4.3):** ≥ 40 orders (aim for 45), ≥ 6 machines (aim for 7), ≥ 3 products with different changeover times, ≥ 3 skill levels (L1–L3), at least one breakdown and one rush order.
- [ ] Keep job durations ≤ 4 h and the total load so a sensible plan fits in about 2 days.
- [ ] **Plant every edge case from §4.4 on purpose, and record where:**
  - [ ] an order whose product can only run on the machine that breaks
  - [ ] an operator with a rare skill who is the only one on their shift
  - [ ] changeover times that differ by direction (A→B ≠ B→A)
  - [ ] a rush order with the same due date as an existing priority-1 order
  - [ ] work in progress that cannot be moved (`movable = false`)
  - [ ] a disruption that makes full on-time delivery impossible
- [ ] Also generate 2 extra disruption files for the evaluation (different machines broken): `disruption_2.csv`, `disruption_3.csv`.
- [ ] `docs/data_card.md` with every Annex D field: name/version, how it was made (script, seed, any AI prompts used), what it contains (tables, row counts, date range), traps and where they are, checks run, known limits, privacy statement (no real data).
- [ ] Push the script and data card. Tell the team the command to regenerate the data. The CSVs themselves stay out of Git.

**Done when:** running the script twice with the same seed gives identical files, and the data card row counts match.

### L3. Loader + validation script (13:45–14:30)
- [ ] `loader.load_table(table, path)`: check required columns exist, parse types, reject bad rows (with reasons), keep good rows. Returns `rows_loaded`, `rows_rejected`, `errors`, `status`.
- [ ] Split `changeovers_skills.csv` into changeovers and operators. Parse `machine_group` into a list. Map shift codes to times.
- [ ] Extra columns are allowed; missing optional columns must not break anything (judges will use files with only the Annex B columns).
- [ ] `loader.load_problem()` builds the `Problem` model from the stored tables.
- [ ] `validation.run_checks(problem)`, covering every check in guide §4.5:
  - [ ] every order's product has a routing
  - [ ] every routing step has at least one capable machine
  - [ ] due dates are after the planning start
  - [ ] the changeover table covers all product pairs used
  - [ ] roster hours are not negative or overlapping
  - [ ] row counts match the data card
- [ ] CLIs: `scripts/load_data.py <folder>` (judges use this) and `scripts/validate_data.py`, which prints a clear PASS/FAIL table. **Save its output for the demo** (`docs/validation_output.txt`).
- [ ] Tests in `tests/test_loader.py`: a missing column, a bad row and a duplicate.

### L4. SQLite store (14:30–14:50)
- [ ] `store.py` with the functions in Shared contracts. Tables: the four data tables, `plans` (run_id, jobs as JSON, created_at) and `traces` (run_id, trace JSON).
- [ ] The database path comes from `config.DB_PATH`.

### L5. `POST /ingest` (14:50–15:05)
- [ ] `routes_ingest.py`: an `APIRouter` taking multipart form data with a CSV `file` plus a JSON field naming the `table` (`orders`, `routings_machines`, `changeovers_skills` or `disruption`).
- [ ] Returns `rows_loaded`, `rows_rejected`, `status` (guide §6). Unknown table name → HTTP 400.
- [ ] Ask Adarsh to add `app.include_router(...)` in `main.py`, or add it yourself after pulling `main`.
- [ ] Test with `curl -F "file=@data/raw/orders.csv" -F 'meta={"table":"orders"}' http://localhost:8000/ingest`.

### L6. Docker (15:05–15:30)
- [ ] One `Dockerfile` (Python 3.11-slim, installs `requirements.txt`).
- [ ] `docker-compose.yml` with two services built from the same image:
  - `api`: generates data if `data/raw` is empty, loads it, starts uvicorn on 8000
  - `ui`: Streamlit on 8501, talking to `http://api:8000`
- [ ] A volume for the SQLite file; `.env` passed in via `env_file`.
- [ ] **Done when:** `docker compose up` from a fresh clone starts both services and `/health` answers.

### L7. Evaluation set and report (cases from 14:00 when you have gaps; run at 15:15–15:50)
- [ ] `eval/cases.json`: ≥ 20 cases, each with a request, optional disruption/weights, and the expected result. Required mix (guide §7):
  - [ ] ≥ 3 disruption scenarios with **different** machines
  - [ ] ≥ 2 rush-order scenarios
  - [ ] ≥ 2 infeasible requests (expected `answer_type: infeasible`)
  - [ ] ≥ 2 trade-off questions with different weights
  - [ ] ≥ 2 attempts to get the LLM to write a plan directly (expected: the plan still comes from the solver, or `refused`)
  - [ ] a few `clarification_needed` (unknown machine) and `refused` (skip skill check) cases
- [ ] `eval/run_eval.py` calls `/analyze` for each case and records:
  - plan validity (share passing the checker)
  - late orders and total lateness
  - overtime and changeovers
  - stability (jobs moved vs the old plan)
  - solve time, and p50/p95 latency
  - explanation faithfulness (`check_facts` ok)
  - LLM calls and tokens
- [ ] Compare two configurations (e.g. stability penalty on vs off, or `gemini-3.5-flash-lite` vs `gemini-3.8-flash`).
- [ ] `eval/report.md`: method (exact match + the checker), results table, which configuration we chose and why, with the numbers.

### Freeze prep (15:50–16:15, whole team)
- [ ] Make sure the data card, validation output and evaluation report are committed.
- [ ] Add your section to `CONTRIBUTIONS.md` and sign `DECLARATION.md`.
- [ ] Run `docker compose up` from a clean checkout one final time before `git tag final`.

---

## Be ready to explain in Q&A
- How the generator works, what the seed does, and where each trap is planted.
- What each validation check catches, and what the loader does with a bad row.
- How `/ingest` lets judges load new data while the system runs.
- What the evaluation measures, why these metrics, and what the numbers showed.
- How Docker compose starts the API and UI.

---

## Shared contracts (identical in all three task files)

After A1 is pushed (~13:05), the source of truth is `backend/app/schemas.py` and `backend/app/config.py`. If this section and the code disagree, the code wins: say so in the group chat.

### Repo layout and owners
```
backend/app/
  config.py          settings from .env                        (Adarsh)
  schemas.py         Pydantic models below                      (Adarsh)
  loader.py          CSV → checked tables → Problem             (Lavanya)
  validation.py      pre-analysis data checks                   (Lavanya)
  store.py           SQLite: tables, plans, traces              (Lavanya)
  routes_ingest.py   POST /ingest (FastAPI APIRouter)           (Lavanya)
  solver.py          CP-SAT solve_schedule                      (Adarsh)
  diff.py            diff_plans                                 (Adarsh)
  graph.py           LangGraph pipeline                         (Adarsh)
  main.py            FastAPI app: /analyze /trace /health       (Adarsh)
  checker.py         validate_plan, compute_kpis                (Ridhi)
  llm.py             Gemini / Ollama / mock switch              (Ridhi)
  explain.py         explanation + fact check                   (Ridhi)
backend/scripts/     generate_data.py, load_data.py, validate_data.py   (Lavanya)
backend/eval/        cases.json, run_eval.py, report.md                 (Lavanya)
backend/tests/       test_<module>.py (each owner tests their own module)
ui/streamlit_app.py  Streamlit UI                                        (Ridhi)
docs/                data_card.md, ai_usage.md, sample_traces/
data/raw/            generated CSVs (gitignored, regenerated by script)
Dockerfile, docker-compose.yml                                           (Lavanya)
```

### Data rules we decided (also documented in the data card and README)
- **Times:** plant local time, format `YYYY-MM-DD HH:MM`. Planning starts at `PLAN_START` (default `2026-10-12 06:00`).
- **Shifts:** A = 06:00–14:00, B = 14:00–22:00, every day. No work 00:00–06:00.
- **Overtime:** a job may run up to 2 h past its operator's shift end; those minutes count as overtime.
- **Skills:** L1 < L2 < L3. An operator qualifies if their level ≥ the step's `skill_required`.
- **`machine_group`:** pipe-separated machine IDs, e.g. `CNC-3|CNC-5`.
- **Job:** one order step = one job, on one machine, with one operator, never split. Duration in minutes = `ceil(qty × minutes_per_unit)`.
- **Changeover:** between consecutive jobs on a machine with different products, the gap must be ≥ `minutes(from → to)`. Same product = 0. First job on a machine needs none.
- **Lateness:** order completion = end of its last step; lateness = max(0, completion − due).
- **WIP (optional extra columns on `orders.csv`):** `wip_step`, `wip_machine`, `wip_operator`, `wip_start`, `wip_end`, `movable`. If `movable` is false, that job is fixed exactly.
- **Customer importance (optional):** `customer_tier` column on `orders.csv`, 1 = key customer.
- **Rush order:** `disruption.csv` row with `kind = rush_order`, `target` = new order ID, plus extra columns `product`, `qty`, `due`, `priority`, `customer`. It cannot start before `at`.
- **Breakdown:** `disruption.csv` row with `kind = breakdown`; machine `target` is unavailable from `at` to `at + duration_h`.
- **`changeovers_skills.csv`** holds two tables in one file: rows with `from_product/to_product/minutes` filled are changeovers; rows with `operator_id/skill/shift` filled are operators.
- The loader must accept files that have **only** the Annex B columns. Every extra column above is optional.

### Pydantic models (`schemas.py`)
```python
Order(order_id: str, product: str, qty: int, due: datetime, priority: int, customer: str,
      customer_tier: int | None = None,
      wip_step: int | None = None, wip_machine: str | None = None, wip_operator: str | None = None,
      wip_start: datetime | None = None, wip_end: datetime | None = None, movable: bool = True)
RoutingStep(product: str, step: int, machines: list[str], minutes_per_unit: float, skill_required: str)
Changeover(from_product: str, to_product: str, minutes: int)
Operator(operator_id: str, skill: str, shift: str, shift_start: time, shift_end: time)
Disruption(event_id: str, kind: Literal["breakdown", "rush_order"], at: datetime, target: str,
           duration_h: float | None = None, product: str | None = None, qty: int | None = None,
           due: datetime | None = None, priority: int | None = None, customer: str | None = None)
Problem(orders: list[Order], routings: list[RoutingStep], changeovers: list[Changeover],
        operators: list[Operator], machines: list[str], plan_start: datetime)

Job(order_id: str, step: int, product: str, machine: str, operator: str,
    start: datetime, end: datetime, changed: bool = False)
Blocked(machine: str, start: datetime, end: datetime)          # breakdown window
Weights(late: float = 10, overtime: float = 3, changeover: float = 1)
KPIs(late_orders: int, total_lateness_h: float, overtime_h: float, changeovers: int, moved_jobs: int = 0)
CheckResult(capacity_ok: bool, skill_ok: bool, changeover_ok: bool, precedence_ok: bool,
            eligibility_ok: bool, shift_ok: bool, wip_ok: bool, breakdown_ok: bool,
            violations: list[str])                              # + property all_ok
Change(order_id: str, step: int, from_: str (JSON key "from"), to: str,
       reason_code: Literal["machine_down", "displaced_by_rush", "precedence", "rebalanced", "new_order"],
       facts: dict)
AnalyzeRequest / AnalyzeResponse: exactly the guide §6 / §6.1 format.
```

### Function signatures
```python
# Lavanya
loader.load_table(table: str, path) -> LoadResult(rows_loaded, rows_rejected, errors, status)
loader.load_problem() -> Problem                       # reads the current tables from the store
validation.run_checks(problem) -> list[dict]           # [{"check", "passed", "detail"}]
store.save_table(name, df) / store.read_table(name) -> DataFrame
store.save_plan(run_id, jobs) / store.latest_plan() -> list[Job] | None
store.save_trace(run_id, trace: dict) / store.get_trace(run_id) -> dict | None

# Adarsh
solver.solve_schedule(problem, weights, *, fixed_jobs=[], blocked=[], not_before={},
                      old_plan=None, deadline=None, allow_overtime=True,
                      time_limit_s=10) -> SolveResult(status, jobs, kpis, solve_s)
diff.diff_plans(old: list[Job], new: list[Job], events: list[Disruption]) -> list[Change]

# Ridhi
checker.validate_plan(problem, jobs, blocked=[], fixed_jobs=[]) -> CheckResult
checker.compute_kpis(problem, jobs, old_plan=None) -> KPIs
llm.complete(system: str, user: str) -> tuple[str, dict]   # (text, {"llm_calls", "tokens"})
explain.explain(facts: dict) -> tuple[str, dict]           # facts = KPIs + changes + check result
explain.check_facts(text: str, facts: dict) -> dict        # {"ok": bool, "unknown_items": [...]}
```

### Git rules
- Each person works only on their own branch: `Adarsh`, `Lavanya`, `Ridhi`. First time: `git fetch` then `git switch <YourName>`.
- Before each task, bring in teammates' merged work: `git pull origin main`.
- To deliver: open a Pull Request from your branch into `main` on GitHub and merge it.
- Merge to `main` at least once an hour. Everyone must have commits (judges check the history).
- Never commit `.env`, keys or `data/raw/`.
