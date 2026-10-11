"""Solver layer 1 tests on the tiny fixture. Rule checks here are deliberately simple;
Ridhi's checker.validate_plan will replace them as the full referee."""

import itertools

from conftest import at

from app.checker import compute_kpis, validate_plan
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


# ---------- Layer 2: changeovers (A4) ----------

def test_solver_avoids_needless_changeovers(tiny_problem):
    # P1 step 1 can go on M2, so the best plan keeps M1 for P2 only: no product switch at all.
    assert solve_schedule(tiny_problem, time_limit_s=5).kpis.changeovers == 0


def test_changeover_gaps_respected_in_the_right_direction(tiny_problem):
    # Force a switch: P1 step 1 may now only run on M1, which also runs P2.
    next(r for r in tiny_problem.routings if r.product == "P1" and r.step == 1).machines = ["M1"]
    minutes = {(c.from_product, c.to_product): c.minutes for c in tiny_problem.changeovers}
    jobs = sorted(solve_schedule(tiny_problem, time_limit_s=5).jobs, key=lambda j: (j.machine, j.start))
    switches = 0
    for a, b in itertools.pairwise(jobs):
        if a.machine == b.machine and a.product != b.product:
            switches += 1
            assert (b.start - a.end).total_seconds() / 60 >= minutes[(a.product, b.product)]
    assert switches >= 1  # M1 must run both P1 and P2 here, so the test is not vacuous


def test_checker_accepts_every_rule_of_solver_plan(tiny_problem):
    result = solve_schedule(tiny_problem, time_limit_s=5)
    check = validate_plan(tiny_problem, result.jobs)
    assert check.all_ok, check.violations


def test_skilled_step_gets_a_qualified_operator(tiny_problem):
    # P1 step 2 needs L2; OP-1 is only L1, so it must never be chosen for it.
    for job in solve_schedule(tiny_problem, time_limit_s=5).jobs:
        if job.product == "P1" and job.step == 2:
            assert job.operator in {"OP-2", "OP-3"}


def test_kpis_come_from_the_checker(tiny_problem):
    result = solve_schedule(tiny_problem, time_limit_s=5)
    assert result.kpis == compute_kpis(tiny_problem, result.jobs)


def test_generated_data_plan_passes_all_rules(tmp_path, tmp_db):
    # Lavanya's 45-order data set: the solver must produce a plan Ridhi's checker accepts
    # on every rule, including operators, shifts and fixed work in progress.
    from app.loader import load_folder, load_problem
    from scripts.generate_data import generate

    generate(seed=42, out=tmp_path)
    load_folder(tmp_path)
    problem = load_problem()
    result = solve_schedule(problem, time_limit_s=5)
    assert result.status in {"OPTIMAL", "FEASIBLE", "GREEDY_FALLBACK"}
    check = validate_plan(problem, result.jobs)
    assert check.all_ok, check.violations[:3]
