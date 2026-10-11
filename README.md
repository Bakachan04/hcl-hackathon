# Production Re-Planner Under Disruption

An AI-augmented production scheduling and disruption recovery system built for the HCLTech Hackathon (October 2026). The system replans job schedules under unexpected events (machine breakdowns, rush orders) using constrained optimization, independent validation, and faithful LLM-powered explanations for plant managers.

---

## 1. Architecture Overview

```text
               +-------------------------------------------+
               |          Streamlit Dashboard (UI)         |
               | (Gantt Chart, KPI Tiles, Controls, Trace) |
               +---------------------+---------------------+
                                     |  HTTP REST
                                     v
               +-------------------------------------------+
               |              FastAPI Backend              |
               |   POST /analyze   POST /ingest   GET /trace|
               +---------------------+---------------------+
                                     |
                                     v
                        +-------------------------+
                        |   LangGraph Pipeline    |
                        +------------+------------+
                                     |
         +---------------------------+---------------------------+
         |                           |                           |
         v                           v                           v
+-------------------+      +-------------------+      +-------------------+
|  CP-SAT Solver    |      |  Plan Checker     |      |  LLM Explain &    |
| (Multi-objective  | ---> |  & KPI Engine     | ---> |  Fact-Checking    |
|  OR-Tools replan) |      | (9 rules referee) |      | (Gemini / Mock)   |
+-------------------+      +-------------------+      +-------------------+
         |                           |                           |
         +---------------------------+---------------------------+
                                     |
                                     v
                        +-------------------------+
                        |      SQLite Store       |
                        | (Tables, Plans, Traces) |
                        +-------------------------+
```

### Module Responsibilities
- **`backend/app/solver.py`**: CP-SAT solver optimizing late orders, overtime hours, and changeover costs under disruptions.
- **`backend/app/checker.py`**: Independent referee validating 9 critical factory constraints and calculating certified KPIs.
- **`backend/app/llm.py`**: Resilient LLM wrapper supporting Google Gemini and an offline mock mode with retry and fallback.
- **`backend/app/explain.py`**: Plain-language plant manager briefing engine equipped with a strict regex fact checker against hallucinations.
- **`ui/streamlit_app.py`**: Usability-focused dashboard with Plotly Gantt charts, breakdown shading, KPI tiles, and objective weight sliders.

---

## 2. Tech Stack & Prerequisites

- **Python:** 3.12+ (tested and developed on Python 3.13)
- **Backend:** FastAPI, Uvicorn, Pydantic v2, HTTPX, python-dotenv
- **Analytics & Solver:** pandas, NumPy, SciPy, scikit-learn, Google OR-Tools
- **Dashboard:** Streamlit, Plotly Express
- **Testing:** pytest (27 unit tests across checker, LLM, and explanation modules)

---

## 3. Setup & Running Locally

### Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### UI Setup

```bash
# In the same virtual environment (or dedicated UI environment):
pip install -r ../ui/requirements.txt
```

### Configuration (`backend/.env`)

Create `backend/.env` (gitignored):

```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=your_gemini_api_key_here
MOCK_LLM=false
PLAN_START=2026-10-12T06:00:00
```

*Note:* If `GEMINI_API_KEY` is not provided or `MOCK_LLM=true`, the system seamlessly runs in **mock mode**, requiring zero network connectivity or external credentials.

### Running Servers

Start the backend API (port 8000):
```bash
uvicorn main:app --reload --port 8000
```

Start the Streamlit dashboard (port 8501):
```bash
streamlit run ui/streamlit_app.py --server.port 8501
```

---

## 4. Docker Deployment

When Docker is installed, launch the containerized application via Docker Compose:

```bash
docker compose up --build
```

- API Docs: `http://localhost:8000/docs`
- Streamlit UI: `http://localhost:8501`

---

## 5. API Reference & Sample Requests

### 1. Health Check
```bash
curl -X GET http://localhost:8000/api/health
```
Response:
```json
{"status": "ok"}
```

### 2. Ingest Data (`POST /ingest` - planned)
```bash
curl -X POST http://localhost:8000/ingest \
  -F "orders=@data/raw/orders.csv" \
  -F "routings=@data/raw/routings.csv" \
  -F "changeovers_skills=@data/raw/changeovers_skills.csv"
```

### 3. Re-plan & Analyze (`POST /analyze`)
```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Replan schedule after CNC-1 breakdown",
    "weights": {
      "late": 10.0,
      "overtime": 3.0,
      "changeover": 1.0
    },
    "avoid_overtime": false,
    "disruption": {
      "event_id": "D-1",
      "kind": "breakdown",
      "at": "2026-10-12T08:00:00",
      "target": "CNC-1",
      "duration_h": 2.0
    }
  }'
```

### 4. Fetch Trace (`GET /trace/{run_id}`)
```bash
curl -X GET http://localhost:8000/trace/run-20261012-081530
```

---

## 6. LLM Configuration & Synthetic Data Note

- **Provider Support:** Google Gemini (`gemini-3.5-flash-lite`), with automatic fallback to local deterministic templates.
- **Privacy & Security:** The free tier of Gemini AI Studio is used for plain-language reasoning. **All datasets, orders, operators, and customer names in this project are 100% synthetic**, containing zero proprietary or personally identifiable information (PII).
- **Fact-Checking Referee:** The LLM is strictly confined to explaining verified results. The `check_facts` module uses regex extraction to guarantee that every order ID, machine ID, operator ID, clock time, and numerical figure matches certified solver facts. Unsupported items trigger an automatic prompt retry followed by a deterministic code-generated fallback.

---

## 7. Core Assumptions & Domain Rules

1. **Planning Horizon:** Plant local time starting at `PLAN_START` (`2026-10-12 06:00`).
2. **Shifts:** Shift A = 06:00–14:00, Shift B = 14:00–22:00. Overnight non-working window: 00:00–06:00.
3. **Overtime:** Jobs may run up to a maximum of 2 hours past an operator's shift end (counted towards the overtime penalty).
4. **Skills:** Ranked hierarchy: $L_1 < L_2 < L_3$. An operator qualifies for a job if their skill level $\ge \text{skill\_required}$.
5. **Job Processing:** Each order step represents an atomic job on one machine with one operator; jobs cannot be pre-empted or split. Duration in minutes equals $\lceil\text{quantity} \times \text{minutes\_per\_unit}\rceil$.
6. **Changeover:** Transitioning between different products on the same machine requires a directional setup gap $\ge \text{changeover\_minutes}$. Consecutive jobs with the same product require 0 gap.
7. **Precedence:** Step $n+1$ of an order must strictly start after step $n$ has completed.
8. **Fixed / WIP Jobs:** Immovable jobs (`movable=False`) remain locked to their scheduled machine, operator, and time window.
9. **Machine Breakdowns:** Scheduled jobs cannot overlap a machine's `Blocked` breakdown window.

---

## 8. Limitations & Known Edge Cases

- **Shift C / Night Shifts:** Current implementation supports Shifts A and B (06:00 to 22:00 plus overtime). True 24/7 continuous operations are not modeled.
- **Machine Maintenance Calendars:** Breakdowns are modeled as discrete disruption events; recurrent preventive maintenance calendars are not loaded automatically.
- **Campus Network Firewalls:** If Gemini endpoints are blocked on restricted networks, mock mode (`MOCK_LLM=true`) should be used for evaluation.
