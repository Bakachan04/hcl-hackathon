# AI-usage disclosure

AI coding assistants were allowed and encouraged (guide §10). This file states where we used them and how we checked the results. Every member can explain the code they submitted.

## Adarsh: setup, shared models, solver, re-planning, pipeline and API

**Assistant:** Claude Code (Anthropic, Claude Opus model) in VS Code.

**Used for:**
- Reading the problem statement and proposing the architecture, build order and task split (`Task_*.md`).
- Writing `app/config.py`, `app/schemas.py`, `app/solver.py`, `app/diff.py`, `app/graph.py`, `app/main.py` endpoints, their tests, and the README sections for architecture, API examples, assumptions and limitations.
- Running experiments and measurements, e.g. solver settings, hint strategies and replan strategies.

**How the output was verified:**
- **Unit and API tests** (`tests/test_solver.py`, `tests/test_analyze.py`). They include cases worked out by hand on a tiny plant, for example "the priority-1 order is on time when two orders compete for one machine".
- **An independent referee:** every solver plan is checked by Ridhi's `checker.validate_plan`, which was written separately from the solver. The API refuses to show a plan that fails any rule.
- **Measured, not assumed:** each design choice was tested on the generated 45-order data and kept only if the numbers improved. Recorded examples:
  - the greedy starting plan as a hint
  - presolve off
  - the repair-style greedy for replans
- Code was reviewed and explained step by step before being committed. One test the assistant wrote was wrong: it assumed a changeover was unavoidable when the solver could avoid it. It was corrected after reading the failure.

## Lavanya: data generator, loader, validation, store, ingest, Docker, evaluation

_To be completed by Lavanya: assistant used, which parts, how verified._

## Ridhi: plan checker, LLM wrapper, explanation and fact check, Streamlit UI

_To be completed by Ridhi: assistant used, which parts, how verified._

## LLM inside the product

- The product's explanation step uses Google Gemini (`LLM_PROVIDER` / `LLM_MODEL`) or a mock mode. It only rephrases facts returned by the tools.
- `explain.check_facts` rejects any ID or number not in those facts.
- The LLM never creates or edits a plan.
