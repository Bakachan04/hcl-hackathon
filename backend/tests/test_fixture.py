"""Sanity checks on the tiny fixture, so solver tests start from known-good data."""

from app.schemas import job_minutes


def test_every_order_product_has_a_routing(tiny_problem):
    routed = {r.product for r in tiny_problem.routings}
    assert all(o.product in routed for o in tiny_problem.orders)


def test_every_routing_machine_exists(tiny_problem):
    for r in tiny_problem.routings:
        assert set(r.machines) <= set(tiny_problem.machines)


def test_changeovers_cover_all_product_pairs(tiny_problem):
    products = {o.product for o in tiny_problem.orders}
    pairs = {(c.from_product, c.to_product) for c in tiny_problem.changeovers}
    assert {(a, b) for a in products for b in products} <= pairs


def test_job_minutes_rounds_up():
    assert job_minutes(60, 1.0) == 60
    assert job_minutes(7, 1.5) == 11  # 10.5 -> 11: never under-plan a job
