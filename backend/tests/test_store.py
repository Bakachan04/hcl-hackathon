from datetime import datetime

import pandas as pd
import pytest

from app import store
from app.schemas import Job


def job(start_hour: int) -> Job:
    return Job(order_id="O-1", step=1, product="P1", machine="CNC-1", operator="OP-01",
               start=datetime(2026, 10, 12, start_hour), end=datetime(2026, 10, 12, start_hour + 1))


def test_table_round_trip_and_replace(tmp_db):
    assert store.read_table("orders").empty
    store.save_table("orders", pd.DataFrame({"order_id": ["O-1", "O-2"], "qty": ["5", ""]}))
    store.save_table("orders", pd.DataFrame({"order_id": ["O-3"], "qty": ["7"]}))
    df = store.read_table("orders")
    assert list(df["order_id"]) == ["O-3"]
    assert store.table_counts()["orders"] == 1


def test_unknown_table_rejected(tmp_db):
    with pytest.raises(ValueError):
        store.save_table("users; DROP TABLE plans", pd.DataFrame())


def test_plans_latest_wins(tmp_db):
    assert store.latest_plan() is None
    store.save_plan("run-1", [job(6)])
    store.save_plan("run-2", [job(8), job(10)])
    latest = store.latest_plan()
    assert [j.start.hour for j in latest] == [8, 10]
    assert store.get_plan("run-1")[0] == job(6)


def test_trace_round_trip(tmp_db):
    assert store.get_trace("nope") is None
    trace = {"run_id": "pl-1", "steps": [{"agent": "solver", "tool": "solve_schedule"}], "tokens": 0}
    store.save_trace("pl-1", trace)
    assert store.get_trace("pl-1") == trace
