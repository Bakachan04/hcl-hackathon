# Evaluation report

> **Status:** the method and the 24 cases are final. The results tables are filled in once `POST /analyze` runs end to end (planned for 15:15).

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

_To be filled from `eval/results/*.json` after the run._

| Metric | Config A | Config B |
|---|---|---|
| Cases passed | | |
| answer_type accuracy | | |
| Plan validity | | |
| Avg late orders | | |
| Avg total lateness (h) | | |
| Avg overtime (h) | | |
| Avg changeovers | | |
| Avg jobs moved (re-plans) | | |
| Solve time p50 / max (s) | | |
| Latency p50 / p95 (s) | | |
| Explanation faithfulness | | |
| LLM calls / tokens | | |

## Configurations compared

_To be decided with the team. Candidates: `gemini-3.5-flash-lite` vs `gemini-3.8-flash`, or the solver's stability penalty on vs off._

## Choice and why

_To be written from the numbers above._

## Failed cases and what they show

_To be written after the run._
