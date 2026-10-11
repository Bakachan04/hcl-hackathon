"""CP-SAT scheduling solver. Owner: Adarsh.

Built in layers (see Task_Adarsh.md):
  Layer 1 (A3): machine choice, one job at a time per machine, step order, lateness.  <- done
  Layer 2 (A4): sequence-dependent changeovers.
  Layer 3 (A5): operators, skills, shifts, overtime.

Time is measured in whole minutes from problem.plan_start.
"""

import itertools
import time as clock
from datetime import timedelta

from ortools.sat.python import cp_model

from app import config
from app.schemas import Job, KPIs, Problem, SolveResult, Weights, job_minutes

# Weights are floats; CP-SAT needs integers. Scaling keeps one decimal of precision.
WEIGHT_SCALE = 10


def _build_jobs(problem: Problem) -> list[dict]:
    """One job per (order, routing step), with its duration and allowed machines."""
    steps_by_product: dict[str, list] = {}
    for r in problem.routings:
        steps_by_product.setdefault(r.product, []).append(r)

    jobs = []
    for order in problem.orders:
        for r in sorted(steps_by_product[order.product], key=lambda s: s.step):
            jobs.append({
                "order": order,
                "step": r.step,
                "product": order.product,
                "duration": job_minutes(order.qty, r.minutes_per_unit),
                "machines": r.machines,
            })
    return jobs


def _minutes(problem: Problem, when) -> int:
    return int((when - problem.plan_start).total_seconds() // 60)


def solve_schedule(problem: Problem, weights: Weights | None = None, *, fixed_jobs=(), blocked=(),
                   not_before=None, old_plan=None, deadline=None, allow_overtime=True,
                   time_limit_s: float | None = None) -> SolveResult:
    # fixed_jobs, blocked, not_before, old_plan, deadline, allow_overtime: used from A5/A6 onwards.
    weights = weights or Weights()
    jobs = _build_jobs(problem)
    model = cp_model.CpModel()

    # Latest time anything could need: every job back to back after the latest due date.
    horizon = (max(_minutes(problem, o.due) for o in problem.orders)
               + sum(j["duration"] for j in jobs) + 24 * 60)

    # --- Machine choice and capacity ---
    intervals_on_machine: dict[str, list] = {m: [] for m in problem.machines}
    for j in jobs:
        j["start"] = model.new_int_var(0, horizon, "")
        j["end"] = model.new_int_var(0, horizon, "")
        j["on"] = {}  # machine -> yes/no variable
        for m in j["machines"]:
            on_m = model.new_bool_var("")
            # The interval only "exists" if on_m is true, so it only blocks machine m then.
            interval = model.new_optional_interval_var(j["start"], j["duration"], j["end"], on_m, "")
            intervals_on_machine[m].append(interval)
            j["on"][m] = on_m
        model.add_exactly_one(j["on"].values())

    for intervals in intervals_on_machine.values():
        model.add_no_overlap(intervals)

    # --- Precedence: steps of one order run in order ---
    by_order: dict[str, list] = {}
    for j in jobs:
        by_order.setdefault(j["order"].order_id, []).append(j)
    for order_jobs in by_order.values():
        for before, after in itertools.pairwise(order_jobs):
            model.add(after["start"] >= before["end"])

    # --- Lateness, weighted by priority and customer importance ---
    lateness_terms = []
    completion_terms = []
    for order_jobs in by_order.values():
        order = order_jobs[0]["order"]
        done = order_jobs[-1]["end"]
        late = model.new_int_var(0, horizon, "")
        model.add(late >= done - _minutes(problem, order.due))  # and late >= 0 from its domain
        factor = config.PRIORITY_FACTOR[order.priority]
        if order.customer_tier == 1:
            factor *= config.KEY_CUSTOMER_FACTOR
        lateness_terms.append(late * factor)
        completion_terms.append(done)

    # Main goal: weighted lateness. Tie-breaker (weight 1): finish orders early, so
    # on-time jobs are not placed at arbitrary late times.
    late_w = round(weights.late * WEIGHT_SCALE) * 100
    model.minimize(late_w * sum(lateness_terms) + sum(completion_terms))

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s or config.SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = 8
    t0 = clock.perf_counter()
    status = solver.solve(model)
    solve_s = round(clock.perf_counter() - t0, 3)
    status_name = solver.status_name(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(status=status_name, solve_s=solve_s)

    plan = []
    for j in jobs:
        machine = next(m for m, on_m in j["on"].items() if solver.value(on_m))
        start = problem.plan_start + timedelta(minutes=solver.value(j["start"]))
        plan.append(Job(order_id=j["order"].order_id, step=j["step"], product=j["product"],
                        machine=machine, operator="UNASSIGNED", start=start,
                        end=start + timedelta(minutes=j["duration"])))
    plan.sort(key=lambda job: (job.machine, job.start))
    return SolveResult(status=status_name, jobs=plan, kpis=_kpis(problem, plan), solve_s=solve_s)


def _kpis(problem: Problem, plan: list[Job]) -> KPIs:
    """Temporary KPI calculation. Replace with Ridhi's checker.compute_kpis once merged."""
    due = {o.order_id: o.due for o in problem.orders}
    done: dict[str, object] = {}
    for job in plan:
        done[job.order_id] = max(done.get(job.order_id, job.end), job.end)
    lateness_h = [max(0.0, (done[o] - due[o]).total_seconds() / 3600) for o in done]
    changeovers = sum(1 for a, b in itertools.pairwise(plan) if a.machine == b.machine and a.product != b.product)
    return KPIs(late_orders=sum(1 for h in lateness_h if h > 0), total_lateness_h=round(sum(lateness_h), 2),
                overtime_h=0.0, changeovers=changeovers)
