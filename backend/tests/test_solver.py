"""Solver layer 1 tests on the tiny fixture. Rule checks here are deliberately simple;
Ridhi's checker.validate_plan will replace them as the full referee."""

import itertools

from conftest import at

from app.schemas import job_minutes
from app.solver import solve_schedule


def _routing(problem, product, step):
    return next(r for r in problem.routings if r.product == product and r.step == step)


def test_solver_finds_a_plan_with_every_job(tiny_problem):
    result = solve_schedule(tiny_problem, time_limit_s=5)
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert len(result.jobs) == 5  # O-1: 2 steps, O-2: 1 step, O-3: 2 steps


def test_jobs_run_on_capable_machines_with_correct_duration(tiny_problem):
    orders = {o.order_id: o for o in tiny_problem.orders}
    for job in solve_schedule(tiny_problem, time_limit_s=5).jobs:
        r = _routing(tiny_problem, job.product, job.step)
        assert job.machine in r.machines
        minutes = (job.end - job.start).total_seconds() / 60
        assert minutes == job_minutes(orders[job.order_id].qty, r.minutes_per_unit)


def test_no_machine_runs_two_jobs_at_once(tiny_problem):
    jobs = sorted(solve_schedule(tiny_problem, time_limit_s=5).jobs, key=lambda j: (j.machine, j.start))
    for a, b in itertools.pairwise(jobs):
        if a.machine == b.machine:
            assert b.start >= a.end


def test_steps_run_in_order(tiny_problem):
    jobs = {(j.order_id, j.step): j for j in solve_schedule(tiny_problem, time_limit_s=5).jobs}
    for (order_id, step), job in jobs.items():
        if (order_id, step + 1) in jobs:
            assert jobs[(order_id, step + 1)].start >= job.end


def test_all_orders_on_time_when_capacity_allows(tiny_problem):
    # Worked out by hand: all 5 jobs fit well before the due dates.
    assert solve_schedule(tiny_problem, time_limit_s=5).kpis.late_orders == 0


def test_priority_1_order_is_protected_when_someone_must_be_late(tiny_problem):
    # O-1 (priority 1) and O-3 (priority 3) both due 09:00. Their step 2 jobs (120 + 80 min)
    # both need M2, so they cannot both make it. The priority-1 order must win.
    for order in tiny_problem.orders:
        if order.order_id in {"O-1", "O-3"}:
            order.due = at(9)
    result = solve_schedule(tiny_problem, time_limit_s=5)
    done = {}
    for job in result.jobs:
        done[job.order_id] = max(done.get(job.order_id, job.end), job.end)
    assert done["O-1"] <= at(9)
    assert done["O-3"] > at(9)
