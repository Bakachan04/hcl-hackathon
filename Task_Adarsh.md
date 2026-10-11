# Tasks: Adarsh

**Project:** Production Re-Planner Under Disruption (HCLTech hackathon, 11 Oct 2026)
**Code freeze:** 16:15 · **Late data drop:** 13:45 · **Team:** Adarsh, Lavanya, Ridhi

**You own:** project setup, the shared data models, the CP-SAT solver, re-planning, the plan diff, the LangGraph pipeline and the `/analyze`, `/trace` and `/health` endpoints.
**Requirements covered:** R2–R7, R11, R12, and the API contract (guide §6).

---

## Dependencies at a glance

| You wait on | For | Until then |
|---|---|---|
| Ridhi: `checker.validate_plan` + `compute_kpis` (~13:45) | Proving each solver layer produces valid plans | Eyeball the output on the tiny fixture |
| Lavanya: `scripts/generate_data.py` (~13:45) | Testing the solver on realistic data (45 orders, 7 machines) | Use the tiny fixture from A2 |
| Lavanya: `loader.load_problem` + `store.py` (~14:30) | The `load_state` step of the pipeline | Build `Problem` directly from the fixture |
| Ridhi: `explain.explain` + `check_facts` (~14:30) | The explanation step of the pipeline | A stub that returns a fixed template text |

| Others wait on you | What | Needed by |
|---|---|---|
| **Lavanya and Ridhi** | **A1: `schemas.py`, `config.py`, folder layout pushed to `main`** | **13:05 (blocks everyone)** |
| Ridhi | A3–A5: real solver plans to test the checker and the Gantt chart | 14:30 |
| Ridhi | A6: `diff_plans` output (list of `Change`) to explain | 15:00 |
| Ridhi, Lavanya | A8: a running `/analyze` for the UI and the evaluation | 15:15 |
| Lavanya | A8: `main.py` with `app.include_router(...)` so `/ingest` can plug in | 14:00 |

---

## Tasks

### A1. Environment reset and shared contracts (12:50–13:05) — **do first, blocks the team**
- [ ] Recreate `backend/.venv` with Python 3.11 (`py -3.11 -m venv .venv`) and update `requirements.txt` pins (see Shared contracts).
- [ ] Delete `frontend/` (we use Streamlit). Add `data/` to `.gitignore`.
- [ ] Create `backend/.env.example` with `LLM_PROVIDER`, `LLM_MODEL`, `MOCK_LLM`, `GEMINI_API_KEY=`, `PLAN_START`, `DB_PATH`.
- [ ] Create the folder layout and empty module files listed in Shared contracts.
- [ ] Write `app/config.py` (reads `.env`) and `app/schemas.py` (all models in Shared contracts).
- [ ] Move the health route to `GET /health`; it must report API, data store and LLM status.
- [ ] Push to `main` and tell the team in the group chat.

**Done when:** `pytest` passes on Python 3.11 and the teammates have pulled `main`.

### A2. Tiny test fixture (13:05–13:15)
- [ ] `backend/tests/fixtures/tiny/`: 3 orders, 2 products, 2 machines, 2 operators, written by hand in the Annex B schema.
- [ ] Lets you build the solver before Lavanya's generator is ready.

### A3. Solver layer 1: machines, precedence, lateness (13:15–13:45)
- [ ] `solver.solve_schedule(...)` per the signature in Shared contracts.
- [ ] One optional interval per (job, eligible machine); exactly one chosen; `NoOverlap` per machine.
- [ ] Steps of an order run in order (precedence).
- [ ] Objective: `late weight × Σ priority factor × lateness` (priority 1 → ×3, 2 → ×2, 3 → ×1; `customer_tier` 1 adds ×2). This is R11.
- [ ] Solver time limit (default 10 s); return `status`, `plan`, `kpis`, `solve_s`.

### A4. Solver layer 2: changeovers (13:45–14:05)
- [ ] Sequence-dependent changeover gap on each machine using `AddCircuit` (direction matters: A→B ≠ B→A).
- [ ] Count changeovers; add `changeover weight × changeovers` to the objective.
- [ ] **Run Ridhi's checker on the output.** Every plan must pass before moving on.

### A5. Solver layer 3: operators, shifts, overtime (14:05–14:30)
- [ ] Each job gets exactly one qualified operator (skill level ≥ required), `NoOverlap` per operator.
- [ ] Job must sit inside the operator's shift window, or extend at most 2 h past shift end (overtime).
- [ ] Add `overtime weight × overtime minutes` to the objective.
- [ ] Test on Lavanya's generated data; checker must report all OK.

### A6. Re-planning and plan diff (14:30–15:00)
- [ ] Jobs that ended before the disruption time `at`, and jobs running at `at` on other machines, are **fixed**. WIP with `movable = false` is fixed.
- [ ] Breakdown → blocked interval on that machine from `at` to `at + duration_h`. A job running on the broken machine at `at` restarts from scratch (documented assumption).
- [ ] Rush order → new order that cannot start before `at`.
- [ ] Stability (R5): penalty for each job that changes machine or moves more than 30 min; pass the old plan to CP-SAT as a hint (`AddHint`).
- [ ] `diff.diff_plans(old, new, events)` → list of `Change` with a `reason_code` computed in code, never by the LLM.

### A7. Infeasible requests and trade-offs (15:00–15:20)
- [ ] Deadline request ("finish all by 17:00") → hard deadline. If the solver returns `INFEASIBLE`, re-solve with a soft deadline and return the closest alternative (answer type `infeasible`).
- [ ] Trade-off ("what if we avoid overtime?") → solve twice (overtime allowed vs not) and return both sets of KPIs.

### A8. Pipeline and API (15:00–15:30, overlaps A7)
- [ ] `graph.py`: LangGraph nodes `parse_request → load_state → solve_schedule → validate_plan → diff_plans → explain → check_facts → save_trace`. Each node appends a step to the trace (Annex C format).
- [ ] Request routing with keyword rules → answer types `plan`, `replan`, `infeasible`, `explanation`, `clarification_needed`, `refused` (guide §6.2).
  - "Skip the skill check" and similar → `refused`.
  - "Write the schedule yourself" → still goes to the solver; the LLM never writes a plan.
  - Unknown machine or order → `clarification_needed`.
- [ ] `POST /analyze` returns exactly the guide §6.1 response format. `GET /trace/{run_id}` returns the stored trace.
- [ ] A plan is returned **only if** the checker says all OK; otherwise return the violations.

### A9. Integration (15:30–15:50)
- [ ] Swap stubs for Lavanya's loader/store and Ridhi's explain/check_facts.
- [ ] Run one request of each answer type end to end and save 3 traces to `docs/sample_traces/`.

### Freeze prep (15:50–16:15, whole team)
- [ ] Write `docs/ai_usage.md`: which parts were AI-assisted and how each was verified.
- [ ] Add your section to `CONTRIBUTIONS.md` and sign `DECLARATION.md`.
- [ ] `git tag final` after `docker compose up` works from a clean checkout.

---

## Be ready to explain in Q&A
- Why a solver (CP-SAT) builds the plan and the LLM only explains it.
- How optional intervals, `NoOverlap` and `AddCircuit` encode machine choice, capacity and changeovers.
- How the weights change the result, and why priority-1 lateness costs more.
- What is frozen during a replan and why; how the stability penalty keeps changes small.
- Why there is one fixed pipeline instead of several agents.

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
- Work on your own branch (`adarsh/solver`, `lavanya/loader`, `ridhi/checker`, …). Pull `main` before starting each task.
- Merge to `main` at least once an hour. Everyone must have commits (judges check the history).
- Never commit `.env`, keys or `data/raw/`.
