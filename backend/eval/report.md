# Evaluation report

> **Status:** final. All 24 cases run against `POST /analyze` on 11-Oct-2026; results below.

## Method

- **Cases:** `eval/cases.json`, 24 cases run in order against `POST /analyze`. C01 builds the baseline plan that later re-plans are measured against.
- **Data:** the seed-42 synthetic pack (`docs/data_card.md`). Disruptions come from `disruption.csv`, `disruption_2.csv` and `disruption_3.csv`, or are given inline.
- **Scoring: exact match + rule checks, no LLM judge.**
  - `answer_type` must exactly match the expected type (or one of an allowed list for the "make the LLM write the plan" cases).
  - Every returned plan is checked twice: once by the `validator` block in the API response, and once by re-running our own checker (`checker.validate_plan`) on the returned jobs, with breakdown windows and non-movable WIP passed in. A plan is valid only if both agree.
  - Case-specific checks: the broken machine has no job during its downtime (`machine_free`), non-movable WIP is untouched (`unchanged_jobs`), the rush order is in the plan (`includes_orders`), R-201 is late as the data card says it must be (`orders_late`), and so on.
- **Explanation faithfulness:** the share of responses whose `check_facts` step in the trace returned `ok: true`. That is, every number and ID in the explanation appears in the tool results.
- **Timing:** solve time is from the trace's `solve_schedule` step. Latency is wall-clock per request, measured by the runner (p50/p95).

### Case mix (guide §7)

| Category | Cases | Minimum |
|---|---|---|
| Starting plan | C01 | — |
| Disruption, different machines | C05 (CNC-3), C06 (CNC-1), C07 (LTH-2), C08 (CNC-3 + rush) | 3 |
| Rush order | C09, C10, C11 | 2 |
| Infeasible | C12, C13, C14 | 2 |
| Trade-off, different weights | C02, C03, C04, C24 | 2 |
| LLM asked to write the plan | C17, C18 | 2 |
| Explanation | C15, C16 | — |
| Clarification needed | C19 (unknown machine), C20 (no machine named) | — |
| Refused (rule breaking) | C21 (skip skill check), C22 (move fixed WIP), C23 (ineligible machine) | — |

## How to run

```powershell
cd backend
.\.venv\Scripts\python.exe eval\run_eval.py --label config-a           # in-process, no server needed
# change the setting in .env (e.g. LLM_MODEL), then:
.\.venv\Scripts\python.exe eval\run_eval.py --label config-b
.\.venv\Scripts\python.exe eval\run_eval.py --compare eval\results\config-a.json eval\results\config-b.json
```

Add `--url http://localhost:8000` to test a running server (for example the Docker one).

## Results

Three configurations, all on the seed-42 pack, run in-process. Raw per-case results: `eval/results/*.json`.

| Metric | **A: solver 10 s (chosen)** | B: solver 3 s | C: solver 10 s + Gemini LLM |
|---|---|---|---|
| Cases passed | **24 / 24** | 24 / 24 | 21 / 24 (run before the A7 fix) |
| answer_type accuracy | 100% | 100% | 87.5% |
| Plan validity (API validator and our own checker agree) | **17 / 17 = 100%** | 17 / 17 = 100% | 17 / 17 = 100% |
| Avg late orders per plan | **7.0** | 11.9 | 5.4 |
| Avg total lateness (h) | **27.3** | 43.8 | 25.1 |
| Avg overtime (h) | **2.6** | 8.3 | 2.6 |
| Avg changeovers | **31.5** | 36.1 | 31.4 |
| Avg jobs moved per re-plan | 56.7 | 42.0 | 46.7 |
| Solve time p50 / max (s) | 10.1 / 11.0 | 3.2 / 3.5 | 10.2 / 10.6 |
| Latency p50 / p95 (s) | 10.6 / 11.9 | 4.1 / 4.8 | 12.6 / 19.5 |
| Explanation faithfulness | 100% | 100% | **100% (19 / 19 LLM explanations)** |
| LLM calls / tokens (whole run) | 0 / 0 (mock) | 0 / 0 (mock) | 20 / 22,214 (~1.1k per request) |

Averages include the stress cases (6 h breakdown on a bottleneck machine, impossible deadlines), which is why late orders are well above the 0–1 of the undisrupted plan.

### Choice and why

- **Solver time limit 10 s (A) over 3 s (B):** A has about 40% fewer late orders (7.0 vs 11.9), 38% less lateness and about 70% less overtime. B is about 6 s faster per request and moves fewer jobs, but lands much worse plans. A replan "within a few minutes" (guide 4.6) is met easily by 10 s.
- **LLM on (C) vs mock (A):** plan quality is the same, because the solver builds the plan either way. The LLM adds about 2 s median latency and about 1.1k tokens per request. In exchange it gives a readable explanation, and every one passed the fact check. We demo with the LLM on and keep mock mode as the fallback.

### History (what the evaluation caught)

- **First run: 17 / 24.**
  - A real bug: a replan after an earlier rush order kept that order's jobs as "fixed" although the order was not in the data, so the plan failed the WIP check (C10, C11).
  - Routing gaps: C20, C22, C23.
- **After fixes: 21 / 24.** Remaining: deadline demands and the trade-off question (C12, C13, C16).
- **After the minimal deadline/trade-off feature: 24 / 24.**

### Limits of this evaluation

- One data set (seed 42) and its 3 disruption files; no large or unseen data. A stress test at 60 and 90 orders (PROJECT notes) gave valid plans with more late orders.
- `infeasible` is judged from the best valid plan found within the time limit, not a mathematical proof.
- CP-SAT runs in parallel, so KPI averages vary by a few percent between runs. Validity and pass/fail did not change.
