# Tasks: Ridhi

**Project:** Production Re-Planner Under Disruption (HCLTech hackathon, 11 Oct 2026)
**Code freeze:** 16:15 · **Late data drop:** 13:45 · **Team:** Adarsh, Lavanya, Ridhi

**You own:** the plan checker and KPI calculation, the LLM wrapper (Gemini / Ollama / mock), the plain-language explanation and its fact checker, the Streamlit UI, and the README.
**Requirements covered:** R8, R9, R10, and the explanation-faithfulness part of the evaluation.

---

## Dependencies at a glance

| You wait on | For | Until then |
|---|---|---|
| Adarsh: A1 `schemas.py` on `main` (~13:05) | The `Job`, `Problem` and `CheckResult` models | Do RD1 (key) and read the rules in Annex A of the guide |
| Lavanya: generated CSVs (~13:45) | Testing the checker on realistic plans | Hand-written plans on the tiny fixture (`tests/fixtures/tiny/`) |
| Adarsh: real solver plans (~14:30) | Confirming the checker agrees with the solver | Hand-written valid and broken plans |
| Adarsh: `diff_plans` output (~15:00) | Real input for `explain()` | Hand-written `facts` dicts in the Shared contracts format |
| Adarsh: `/analyze` running (~15:15) | Wiring the UI to live data | Build the UI against a saved sample response (guide §6.1 JSON) |
| Lavanya: `store.get_trace()` (~15:00) | The UI's trace view | Show the trace from the `/analyze` response |

| Others wait on you | What | Needed by |
|---|---|---|
| **Adarsh** | **RD2: `checker.validate_plan` + `compute_kpis`** (he checks every solver layer with it) | **13:45** |
| Lavanya | RD2: checker + KPIs for the evaluation metrics | 15:15 |
| Adarsh | RD4: `explain.explain` + `check_facts` for the pipeline | 14:30 |
| Whole team | RD1: a working Gemini key in `backend/.env` | 13:15 |

---

## Tasks

### RD1. LLM key (12:50–13:05)
- [ ] Get a free key at Google AI Studio (aistudio.google.com) → "Get API key". We use `gemini-3.5-flash-lite`.
- [ ] Put it in `backend/.env` as `GEMINI_API_KEY=...`. **Never commit it, never paste it in chat.** Share it with the team in person.
- [ ] Test one call from the campus network. If Gemini is blocked, tell the team at once (fallback: Ollama `qwen2.5:7b-instruct`, which is slow on our laptops).

### RD2. Plan checker + KPIs (13:05–13:45) — **Adarsh needs this to verify the solver**
This is our own referee, written **independently of the solver**. If the two disagree, one of them has a bug. It's worth 25 points, so be thorough.
- [ ] `checker.validate_plan(problem, jobs, blocked, fixed_jobs)` returns a `CheckResult`. Each rule fills its own flag and adds readable messages to `violations`:
  - [ ] **capacity**: no two jobs overlap on the same machine
  - [ ] **eligibility**: each job's machine is in its routing step's `machines` list
  - [ ] **changeover**: on each machine, the gap between consecutive jobs with different products is ≥ the changeover minutes for that direction
  - [ ] **precedence**: step *n+1* starts after step *n* of the same order ends
  - [ ] **skill**: the operator's level ≥ `skill_required`
  - [ ] **shift**: the job sits inside the operator's shift, plus at most 2 h of overtime; no operator works two jobs at once
  - [ ] **WIP**: fixed jobs appear exactly as given
  - [ ] **breakdown**: no job overlaps a `Blocked` window on its machine
  - [ ] every order step is scheduled exactly once, and its duration = `ceil(qty × minutes_per_unit)`
- [ ] `checker.compute_kpis(problem, jobs, old_plan=None)` → `late_orders`, `total_lateness_h`, `overtime_h`, `changeovers`, `moved_jobs` (jobs whose machine or start differs from `old_plan`).
- [ ] `tests/test_checker.py`: one valid hand-written plan that passes, and **one broken plan per rule** that must fail with the right flag. Include the guide's Annex A example: putting O-118 on a machine that doesn't support the product must fail eligibility.

**Done when:** all tests pass and Adarsh has pulled it.

### RD3. LLM wrapper (13:45–14:00)
- [ ] `llm.complete(system, user)` → `(text, {"llm_calls": 1, "tokens": n})`.
- [ ] Switch on `config.LLM_PROVIDER` (`gemini`, `ollama`, `mock`) and `LLM_MODEL`. `MOCK_LLM=true` returns a fixed template without any network call.
- [ ] Timeout plus one retry. On failure, return the template text and record that the fallback was used.

### RD4. Explanation + fact checker (14:00–14:30)
The LLM **only explains**. It never creates or edits a plan (Annex A).
- [ ] `explain.explain(facts)`: the prompt contains only `facts` (KPIs, the list of `Change` items with `reason_code`, the check result, the weights). The system prompt tells the model to use only these facts, write 3–6 short sentences for a plant manager, and say "not in the data" if asked anything else.
- [ ] `explain.check_facts(text, facts)`: pull every order ID, machine ID, operator ID, clock time and number out of the text (regex), and check each appears in `facts`. Return `{"ok": bool, "unknown_items": [...]}`.
- [ ] If the check fails: retry once with the unknown items listed. If it fails again, use a template explanation built in code from `facts`.
- [ ] `tests/test_explain.py`: a faithful text passes; a text with an invented order ID or number fails.

### RD5. Streamlit UI (14:30–15:15, then wire to live API 15:15–15:40)
Keep it simple; the UI is scored only on usability.
- [ ] `ui/streamlit_app.py`, reading the API address from env `API_URL` (default `http://localhost:8000`).
- [ ] A request box plus buttons for the demo questions: "Build today's schedule", "Load disruption and re-plan", "What if we avoid overtime?", "Why did order X move?".
- [ ] Weight sliders (late, overtime, changeover) sent with the request (R6: the weights are visible and changeable).
- [ ] **Gantt chart (R10):** `plotly.express.timeline` with machines on the y-axis and orders as bars; changed jobs highlighted in a different color; breakdown windows shaded.
- [ ] KPI tiles, checker result (green/red per rule), the changes table, the explanation text, and the `run_id` with its trace (raw JSON in an expander).
- [ ] Health indicator from `GET /health`.

### RD6. README (15:40–16:00)
Guide §8 requires all of these:
- [ ] architecture diagram (a text diagram is fine)
- [ ] setup and run steps, both local and `docker compose up`
- [ ] sample `curl` commands for `/analyze`, `/ingest`, `/health`, `/trace/{id}`
- [ ] LLM choice (`LLM_PROVIDER` / `LLM_MODEL`) and its data note: the free Gemini tier may use requests, and all our data is synthetic
- [ ] assumptions (copy the data rules from Shared contracts), limitations, known edge cases

Ask Adarsh and Lavanya to check their sections.

### Freeze prep (15:50–16:15, whole team)
- [ ] Add your section to `CONTRIBUTIONS.md` and sign `DECLARATION.md`.
- [ ] Final demo run-through in the UI.

---

## Be ready to explain in Q&A
- Why the checker is separate from the solver, and how each rule is tested.
- How KPIs and "jobs moved" are calculated.
- Why the LLM sees only computed facts, and how `check_facts` catches invented numbers.
- What happens when the LLM fails, is slow or has no key (mock and fallback).
- How the UI shows changes and how the weights flow to the solver.

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
