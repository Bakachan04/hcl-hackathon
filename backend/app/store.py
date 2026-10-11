"""SQLite store: data tables, plans, traces. Owner: Lavanya.

One SQLite file at config.DB_PATH. The four data tables are stored as loaded (cleaned
text columns); `plans` and `traces` keep JSON per run_id.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime

import pandas as pd

from app import config
from app.schemas import Job

DATA_TABLES = ("orders", "routings_machines", "changeovers_skills", "disruption")


def _connect() -> sqlite3.Connection:
    # Read config at call time so tests can point DB_PATH at a temp file.
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS plans (run_id TEXT PRIMARY KEY, jobs TEXT NOT NULL,"
                 " created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS traces (run_id TEXT PRIMARY KEY, trace TEXT NOT NULL)")
    return conn


def _check_name(name: str) -> None:
    if name not in DATA_TABLES:
        raise ValueError(f"unknown table {name!r}; expected one of {', '.join(DATA_TABLES)}")


# ---------- Data tables ----------

def save_table(name: str, df: pd.DataFrame) -> None:
    """Replace the stored table with `df`."""
    _check_name(name)
    with closing(_connect()) as conn, conn:
        df.to_sql(name, conn, if_exists="replace", index=False)


def read_table(name: str) -> pd.DataFrame:
    """The stored table as text columns ('' for empty). Empty frame if never loaded."""
    _check_name(name)
    with closing(_connect()) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                              (name,)).fetchone()
        if not exists:
            return pd.DataFrame()
        return pd.read_sql_query(f'SELECT * FROM "{name}"', conn, dtype=str).fillna("")


def table_counts() -> dict[str, int]:
    return {name: len(read_table(name)) for name in DATA_TABLES}


# ---------- Plans ----------

def save_plan(run_id: str, jobs: list[Job]) -> None:
    payload = json.dumps([job.model_dump(mode="json") for job in jobs])
    with closing(_connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO plans VALUES (?, ?, ?)",
                     (run_id, payload, datetime.now().isoformat(timespec="microseconds")))


def get_plan(run_id: str) -> list[Job] | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT jobs FROM plans WHERE run_id = ?", (run_id,)).fetchone()
    return [Job(**j) for j in json.loads(row[0])] if row else None


def latest_plan() -> list[Job] | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT jobs FROM plans ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    return [Job(**j) for j in json.loads(row[0])] if row else None


# ---------- Traces ----------

def save_trace(run_id: str, trace: dict) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO traces VALUES (?, ?)",
                     (run_id, json.dumps(trace, default=str)))


def get_trace(run_id: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT trace FROM traces WHERE run_id = ?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None
