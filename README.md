# HCL Hackathon

Full-stack starter for the HCLTech AI Engineer hackathon: a React dashboard backed by a Python API, with data processing and machine learning built in.

> **Status:** environment scaffold. The problem statement hasn't been released yet; features will be added once it is.

## Tech stack

| Layer | Tools |
|---|---|
| Frontend | React 19, Vite, Recharts (charts), Lucide React (icons), Oxlint |
| Backend | Python 3.14, FastAPI, Uvicorn |
| Data / ML | pandas, NumPy, scikit-learn, SciPy |
| Utilities | SQLite (built into Python), python-dotenv, httpx |
| Testing | pytest |

## Project structure

```
hcl-hackathon/
├── backend/
│   ├── main.py            # FastAPI app and routes
│   ├── requirements.txt   # Python dependencies (pinned)
│   ├── pytest.ini
│   └── tests/
└── frontend/
    ├── src/               # React components
    ├── vite.config.js     # dev server + /api proxy to the backend
    └── package.json
```

## Prerequisites

- Python 3.12+ (tested on 3.14)
- Node.js 20+ and npm (tested on Node 22)
- Git

## Setup

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS/Linux, use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`.

### Frontend

```powershell
cd frontend
npm install
```

## Running locally

Start both servers, each in its own terminal.

**Backend** (http://127.0.0.1:8000), from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

**Frontend** (http://localhost:5173), from `frontend/`:

```powershell
npm run dev
```

During development, the Vite dev server forwards every request under `/api` to the backend (see `frontend/vite.config.js`), so the frontend calls relative URLs such as `fetch('/api/health')` and no CORS setup is needed.

## API

Interactive API docs are served at http://127.0.0.1:8000/docs while the backend is running.

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check, returns `{"status": "ok"}` |

```powershell
curl http://127.0.0.1:8000/api/health
```

## Configuration

No environment variables are required yet. When they are (for example an LLM API key), they go in `backend/.env`, which Git ignores, and a `backend/.env.example` with placeholder values will be committed:

```
EXAMPLE_API_KEY=your-key-here
```

## Testing and linting

```powershell
# backend, from backend/
.\.venv\Scripts\python.exe -m pytest

# frontend, from frontend/
npm run lint
npm run build
```

## Known limitations

- The Vite `/api` proxy works only in development (`npm run dev`). A production deployment would need the backend to serve the built frontend, a reverse proxy, or CORS configuration.
- The chart on the start page uses static sample data to check rendering.
