"""Shared test data. pytest gives `tiny_problem` / `tmp_db` to any test that names them as an argument.

Tiny plant, small enough to check a schedule by hand:
  - P1 has 2 steps: step 1 on M1 or M2 (machine choice), step 2 only on M2, needs L2.
  - P2 has 1 step, only on M1.
  - Changeovers differ by direction: P1->P2 30 min, P2->P1 15 min.
  - OP-1 (L1, shift A), OP-2 (L2, shift A), OP-3 (L2, shift B).
"""

from datetime import datetime, time

import pytest

from app import config
from app.schemas import Changeover, Operator, Order, Problem, RoutingStep

DAY = datetime(2026, 10, 12)


def at(hh: int, mm: int = 0) -> datetime:
    return DAY.replace(hour=hh, minute=mm)


@pytest.fixture
def tiny_problem() -> Problem:
    return Problem(
        plan_start=at(6),
        machines=["M1", "M2"],
        orders=[
            # durations: step 1 = 60 min, step 2 = 120 min
            Order(order_id="O-1", product="P1", qty=60, due=at(10), priority=1, customer="Acme"),
            # 120 min
            Order(order_id="O-2", product="P2", qty=80, due=at(12), priority=2, customer="Bolt"),
            # step 1 = 40 min, step 2 = 80 min
            Order(order_id="O-3", product="P1", qty=40, due=at(13), priority=3, customer="Core"),
        ],
        routings=[
            RoutingStep(product="P1", step=1, machines=["M1", "M2"], minutes_per_unit=1.0, skill_required="L1"),
            RoutingStep(product="P1", step=2, machines=["M2"], minutes_per_unit=2.0, skill_required="L2"),
            RoutingStep(product="P2", step=1, machines=["M1"], minutes_per_unit=1.5, skill_required="L1"),
        ],
        changeovers=[
            Changeover(from_product="P1", to_product="P2", minutes=30),
            Changeover(from_product="P2", to_product="P1", minutes=15),
            Changeover(from_product="P1", to_product="P1", minutes=0),
            Changeover(from_product="P2", to_product="P2", minutes=0),
        ],
        operators=[
            Operator(operator_id="OP-1", skill="L1", shift="A", shift_start=time(6), shift_end=time(14)),
            Operator(operator_id="OP-2", skill="L2", shift="A", shift_start=time(6), shift_end=time(14)),
            Operator(operator_id="OP-3", skill="L2", shift="B", shift_start=time(14), shift_end=time(22)),
        ],
    )


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the store at a fresh SQLite file for one test."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    return path
