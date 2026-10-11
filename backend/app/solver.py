"""CP-SAT scheduling solver. Owner: Adarsh.

Built in layers (see Task_Adarsh.md):
  Layer 1 (A3): machine choice, one job at a time per machine, step order, lateness.
  Layer 2 (A4): sequence-dependent changeovers.
  Layer 3 (A5): operators (skill, shift windows, one job at a time), overtime, fixed WIP.

Time is measured in whole minutes from problem.plan_start.

Weight units (visible and changeable via Weights):
  late       = cost per hour an order is late (times its priority factor)
  overtime   = cost per hour of overtime
  changeover = cost per changeover

Scheduling assumptions (also listed in the API response):
  - An operator works their shift every day, plus at most config.OVERTIME_MAX_H overtime.
  - A job must START inside the regular shift; overtime only finishes a running job.
  - Jobs never split: one machine and one operator for the whole job.

How a solve works:
  1. greedy_plan() builds a simple valid plan in milliseconds (earliest due date first).
  2. That plan is handed to CP-SAT as a starting point (a "hint").
  3. CP-SAT improves it until it proves optimality or hits the time limit.
  4. If CP-SAT finds nothing in time, the greedy plan is returned (GREEDY_FALLBACK).
"""

import itertools
import time as clock
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from app import config
from app.checker import compute_kpis
from app.schemas import Job, Problem, SolveResult, Weights, job_minutes, skill_rank

# Weights are floats; CP-SAT needs integers. Scaling keeps one decimal of precision.
WEIGHT_SCALE = 10
# The "finish early" tie-breaker must never outweigh a real cost, so real costs are multiplied up.
MAIN_COST_SCALE = 100
# Tuned in A4 on the 45-order data set (see PROJECT_LOG): the tie-breaker keeps plans
# compact at no measurable cost; 8 workers is safe inside a Docker container.
TIE_BREAKER = True
NUM_WORKERS = 8
# The greedy plan looks at most this many days ahead for a free shift.
MAX_DAYS = 30
# Replan stability (R5): cost of moving a job, per hour moved and per machine change.
STABILITY_WEIGHT = 1


# ---------------------------------------------------------------- data preparation

def _minutes(problem: Problem, when: datetime) -> int:
    return int((when - problem.plan_start).total_seconds() // 60)


def _build_jobs(problem: Problem) -> list[dict]:
    """One job per (order, routing step), with duration, allowed machines and operators."""
    steps_by_product: dict[str, list] = {}
    for r in problem.routings:
        steps_by_product.setdefault(r.product, []).append(r)

    jobs = []
    for order in problem.orders:
        for r in sorted(steps_by_product[order.product], key=lambda s: s.step):
            jobs.append({
                "id": len(jobs),
                "order": order,
                "step": r.step,
                "product": order.product,
                "duration": job_minutes(order.qty, r.minutes_per_unit),
                "machines": r.machines,
                "operators": [o.operator_id for o in problem.operators
                              if skill_rank(o.skill) >= skill_rank(r.skill_required)],
            })
    return jobs


def _by_order(jobs: list[dict]) -> dict[str, list]:
    by_order: dict[str, list] = {}
    for j in jobs:
        by_order.setdefault(j["order"].order_id, []).append(j)
    return by_order


def _setup_fn(problem: Problem):
    """Returns setup(a, b): changeover minutes from product a to product b."""
    minutes = {(c.from_product, c.to_product): c.minutes for c in problem.changeovers}
    # A missing pair is flagged by validation; until fixed, assume the worst known changeover.
    worst = max(minutes.values(), default=0)

    def setup(a: str, b: str) -> int:
        return 0 if a == b else minutes.get((a, b), worst)

    return setup


def _window_fn(problem: Problem):
    """Returns window(operator_id, day) -> (start, regular_end, overtime_end) in minutes,
    or None if that shift is already over at the planning start."""
    ops = {o.operator_id: o for o in problem.operators}
    first_day = problem.plan_start.date()
    overtime = int(config.OVERTIME_MAX_H * 60)

    def window(op_id: str, day: int):
        op = ops[op_id]
        date = first_day + timedelta(days=day)
        start = _minutes(problem, datetime.combine(date, op.shift_start))
        end = _minutes(problem, datetime.combine(date, op.shift_end))
        if end <= start:  # a night shift that ends after midnight
            end += 24 * 60
        if end <= 0:      # this shift finished before planning starts
            return None
        return max(start, 0), end, end + overtime

    return window


def _fixed_jobs(problem: Problem, fixed_jobs) -> dict[tuple[str, int], Job]:
    """Jobs that must not move: unmovable work in progress, plus any passed in (A6 replans)."""
    fixed = {(j.order_id, j.step): j for j in fixed_jobs}
    for o in problem.orders:
        if not o.movable and o.wip_step is not None and (o.order_id, o.wip_step) not in fixed:
            fixed[(o.order_id, o.wip_step)] = Job(
                order_id=o.order_id, step=o.wip_step, product=o.product, machine=o.wip_machine,
                operator=o.wip_operator, start=o.wip_start, end=o.wip_end)
    return fixed


# ---------------------------------------------------------------- solver

def solve_schedule(problem: Problem, weights: Weights | None = None, *, fixed_jobs=(), blocked=(),
                   not_before=None, earliest_start=None, old_plan=None, allow_overtime=True,
                   time_limit_s: float | None = None) -> SolveResult:
    """Replan inputs (A6):
      fixed_jobs      jobs that must stay exactly as they are (done or running)
      blocked         machine breakdown windows
      not_before      {order_id: datetime} e.g. a rush order cannot start before it arrives
      earliest_start  nothing that is not fixed may start before this (the disruption time)
      old_plan        previous plan; moving a job away from it costs STABILITY_WEIGHT
    """
    weights = weights or Weights()
    jobs = _build_jobs(problem)
    setup = _setup_fn(problem)
    window = _window_fn(problem)
    fixed = _fixed_jobs(problem, fixed_jobs)
    blocked_min = [(b.machine, max(0, _minutes(problem, b.start)), _minutes(problem, b.end))
                   for b in blocked if _minutes(problem, b.end) > 0]
    for j in jobs:
        j["fixed"] = fixed.get((j["order"].order_id, j["step"]))
        release = _minutes(problem, earliest_start) if earliest_start and not j["fixed"] else 0
        if not_before and j["order"].order_id in not_before:
            release = max(release, _minutes(problem, not_before[j["order"].order_id]))
        j["release"] = max(0, release)

    # The greedy plan runs first: it also tells us how many days the plan needs.
    placed, sequence = greedy_plan(problem, jobs, setup, window, allow_overtime, blocked_min)
    last_due_day = (max(o.due for o in problem.orders).date() - problem.plan_start.date()).days
    last_used_day = max((p[3] for p in placed.values()), default=0)
    n_days = max(last_due_day, last_used_day) + 1

    model = cp_model.CpModel()
    horizon = max(w[2] for o in problem.operators for d in range(n_days) if (w := window(o.operator_id, d)))

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

    # Breakdowns: a fixed "busy" block on the machine that no job may overlap.
    for m, b_start, b_end in blocked_min:
        if m in intervals_on_machine:
            intervals_on_machine[m].append(model.new_fixed_size_interval_var(b_start, b_end - b_start, ""))

    for intervals in intervals_on_machine.values():
        model.add_no_overlap(intervals)

    for j in jobs:
        if not j["fixed"] and j["release"]:
            model.add(j["start"] >= j["release"])

    changeover_arcs, arcs_by_machine = _add_changeovers(model, problem, jobs, setup)

    # --- Operators: skill, shift window, one job at a time, overtime ---
    overtime_terms = _add_operators(model, problem, jobs, window, n_days, allow_overtime)

    # --- Fixed jobs (unmovable work in progress) ---
    for j in jobs:
        f = j["fixed"]
        if f is None:
            continue
        model.add(j["start"] == _minutes(problem, f.start))
        model.add(j["on"][f.machine] == 1)
        day = (f.start.date() - problem.plan_start.date()).days
        model.add(j["op"][(f.operator, day)] == 1)

    # --- Precedence: steps of one order run in order ---
    by_order = _by_order(jobs)
    for order_jobs in by_order.values():
        for before, after in itertools.pairwise(order_jobs):
            model.add(after["start"] >= before["end"])

    # --- Lateness, weighted by priority and customer importance ---
    lateness_terms = []
    completion_terms = []
    late_vars = {}
    for order_jobs in by_order.values():
        order = order_jobs[0]["order"]
        done = order_jobs[-1]["end"]
        due = _minutes(problem, order.due)
        late = model.new_int_var(0, horizon, "")
        model.add(late >= done - due)  # and late >= 0 from its domain
        late_vars[order.order_id] = (late, order_jobs[-1], due)
        factor = config.PRIORITY_FACTOR[order.priority]
        if order.customer_tier == 1:
            factor *= config.KEY_CUSTOMER_FACTOR
        lateness_terms.append(late * factor)
        completion_terms.append(done)

    # --- Stability: moving a job away from the old plan costs something (R5) ---
    moved_minutes, machine_changes, old_starts = [], [], {}
    old = {(oj.order_id, oj.step): oj for oj in (old_plan or [])}
    for j in jobs:
        oj = old.get((j["order"].order_id, j["step"]))
        if oj is None or j["fixed"]:
            continue
        old_start = old_starts[j["id"]] = _minutes(problem, oj.start)
        dev = j["moved"] = model.new_int_var(0, horizon, "")
        model.add(dev >= j["start"] - old_start)
        model.add(dev >= old_start - j["start"])
        moved_minutes.append(dev)
        if oj.machine in j["on"]:
            machine_changes.append(1 - j["on"][oj.machine])

    # Main goal, all in "weight-hours" (times are in minutes, so a changeover counts as
    # 60 minutes of its weight). Tie-breaker (weight 1): finish orders early.
    per_minute = WEIGHT_SCALE * MAIN_COST_SCALE
    model.minimize(round(weights.late * per_minute) * sum(lateness_terms)
                   + round(weights.overtime * per_minute) * sum(overtime_terms)
                   + round(weights.changeover * per_minute) * 60 * sum(changeover_arcs)
                   + round(STABILITY_WEIGHT * per_minute) * (sum(moved_minutes) + 60 * sum(machine_changes))
                   + (sum(completion_terms) if TIE_BREAKER else 0))

    # --- Start from the greedy plan, then let CP-SAT improve it ---
    _add_hint(model, jobs, arcs_by_machine, placed, sequence, late_vars, window)
    for j in jobs:
        if "moved" in j:
            model.add_hint(j["moved"], abs(placed[j["id"]][1] - old_starts[j["id"]]))

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s or config.SOLVER_TIME_LIMIT_S
    solver.parameters.num_workers = NUM_WORKERS
    # Presolve on this model takes most of the time limit and drops the greedy hint
    # (measured in A5: fallback-only with it, 3 -> 1 late orders without it).
    solver.parameters.cp_model_presolve = False
    t0 = clock.perf_counter()
    status = solver.solve(model)
    solve_s = round(clock.perf_counter() - t0, 3)
    status_name = solver.status_name(status)

    if status == cp_model.INFEASIBLE:
        return SolveResult(status=status_name, solve_s=solve_s)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        plan = []
        for j in jobs:
            machine = next(m for m, on_m in j["on"].items() if solver.value(on_m))
            operator = next(op for (op, _), x in j["op"].items() if solver.value(x))
            plan.append(_job(problem, j, machine, operator, solver.value(j["start"])))
    else:
        # Out of time with no solution: fall back to the valid greedy plan.
        status_name = "GREEDY_FALLBACK"
        plan = [_job(problem, j, m, op, start) for j in jobs for (m, start, op, _) in [placed[j["id"]]]]
    plan.sort(key=lambda job: (job.machine, job.start))
    # KPIs come from the independent checker, not from the solver's own view of the plan.
    return SolveResult(status=status_name, jobs=plan, kpis=compute_kpis(problem, plan), solve_s=solve_s)


def _job(problem: Problem, j: dict, machine: str, operator: str, start_min: int) -> Job:
    start = problem.plan_start + timedelta(minutes=start_min)
    return Job(order_id=j["order"].order_id, step=j["step"], product=j["product"], machine=machine,
               operator=operator, start=start, end=start + timedelta(minutes=j["duration"]))


def _add_changeovers(model: cp_model.CpModel, problem: Problem, jobs: list[dict], setup):
    """Order the jobs on each machine with a circuit, and leave changeover time between them.

    Per machine, node 0 is a dummy "start/end of the day" and nodes 1..n are the jobs that
    could run there. Each arc i -> j is a yes/no variable: "j runs directly after i".
    add_circuit forces the chosen arcs to form one loop, i.e. one valid job order.
    Returns the arcs that switch product (to count changeovers), and every arc per machine
    keyed by (from job id, to job id), with None meaning the dummy start/end node.
    """
    switching_arcs = []
    arcs_by_machine: dict[str, dict] = {}
    for m in problem.machines:
        candidates = [j for j in jobs if m in j["on"]]
        if not candidates:
            continue
        arcs = []
        named = arcs_by_machine[m] = {}
        for i, a in enumerate(candidates, start=1):
            named[(None, a["id"])] = first = model.new_bool_var("")  # a runs first on m
            named[(a["id"], None)] = last = model.new_bool_var("")   # a runs last on m
            arcs += [(0, i, first), (i, 0, last)]
            arcs.append((i, i, ~a["on"][m]))                         # self-loop: a not on m
            for k, b in enumerate(candidates, start=1):
                if i == k:
                    continue
                named[(a["id"], b["id"])] = follows = model.new_bool_var("")  # b directly after a
                arcs.append((i, k, follows))
                model.add(b["start"] >= a["end"] + setup(a["product"], b["product"])).only_enforce_if(follows)
                if a["product"] != b["product"]:
                    switching_arcs.append(follows)
        named[(None, None)] = empty = model.new_bool_var("")         # machine stays empty
        arcs.append((0, 0, empty))
        model.add_circuit(arcs)
    return switching_arcs, arcs_by_machine


def _add_operators(model: cp_model.CpModel, problem: Problem, jobs: list[dict], window, n_days: int,
                   allow_overtime: bool) -> list:
    """Each job gets exactly one (qualified operator, day). Same pattern as machines:
    a yes/no variable per option plus an optional interval, so NoOverlap per operator
    stops an operator doing two jobs at once. Returns per-job overtime minute variables."""
    intervals_of_operator: dict[str, list] = {o.operator_id: [] for o in problem.operators}
    overtime_terms = []
    for j in jobs:
        j["op"] = {}  # (operator, day) -> yes/no variable
        j["overtime"] = model.new_int_var(0, int(config.OVERTIME_MAX_H * 60), "")
        overtime_terms.append(j["overtime"])
        for op_id in j["operators"]:
            for day in range(n_days):
                w = window(op_id, day)
                if w is None:
                    continue
                start, regular_end, overtime_end = w
                if j["duration"] > (overtime_end if allow_overtime else regular_end) - start:
                    continue  # job can never fit in this window
                x = j["op"][(op_id, day)] = model.new_bool_var("")
                intervals_of_operator[op_id].append(
                    model.new_optional_interval_var(j["start"], j["duration"], j["end"], x, ""))
                model.add(j["start"] >= start).only_enforce_if(x)
                model.add(j["start"] < regular_end).only_enforce_if(x)  # start inside the shift
                model.add(j["end"] <= (overtime_end if allow_overtime else regular_end)).only_enforce_if(x)
                model.add(j["overtime"] >= j["end"] - regular_end).only_enforce_if(x)
        model.add_exactly_one(j["op"].values())
    for intervals in intervals_of_operator.values():
        model.add_no_overlap(intervals)
    return overtime_terms


# ---------------------------------------------------------------- greedy plan and hint

def greedy_plan(problem: Problem, jobs: list[dict], setup, window, allow_overtime: bool = True,
                blocked_min=()):
    """Simple dispatching rule: fixed jobs first; then orders by earliest due date (then
    priority); each step on the (machine, operator) pair where it finishes soonest, inside
    a shift, after any changeover.

    Always gives a valid plan in milliseconds. Used as the solver's starting point (hint)
    and as a fallback if the solver finds nothing.
    Returns ({job id: (machine, start, operator, day)}, {machine: [job ids in run order]}).
    """
    m_free = dict.fromkeys(problem.machines, 0)
    m_last: dict[str, str | None] = dict.fromkeys(problem.machines)
    op_free = {o.operator_id: 0 for o in problem.operators}
    sequence: dict[str, list] = {m: [] for m in problem.machines}
    placed: dict[int, tuple] = {}

    def earliest_in_shift(op_id: str, t: int, duration: int):
        """First (start, day) >= t where the job fits in one of the operator's shifts."""
        for day in range(MAX_DAYS):
            w = window(op_id, day)
            if w is None:
                continue
            start = max(t, w[0])
            limit = w[2] if allow_overtime else w[1]
            if start < w[1] and start + duration <= limit:
                return start, day
        return None

    # Fixed jobs block their machine and operator from the start.
    for j in sorted((j for j in jobs if j["fixed"]), key=lambda j: j["fixed"].start):
        f = j["fixed"]
        start = _minutes(problem, f.start)
        day = (f.start.date() - problem.plan_start.date()).days
        placed[j["id"]] = (f.machine, start, f.operator, day)
        sequence[f.machine].append(j["id"])
        m_free[f.machine] = max(m_free[f.machine], start + j["duration"])
        m_last[f.machine] = j["product"]
        op_free[f.operator] = max(op_free[f.operator], start + j["duration"])

    def earliest_slot(m: str, op_id: str, t: int, duration: int):
        """Earliest start >= t inside the operator's shift that avoids breakdowns on m."""
        for _ in range(50):
            slot = earliest_in_shift(op_id, t, duration)
            if slot is None:
                return None
            clash = [be for bm, bs, be in blocked_min if bm == m and slot[0] < be and slot[0] + duration > bs]
            if not clash:
                return slot
            t = max(clash)
        return None

    orders = sorted(_by_order(jobs).values(), key=lambda js: (js[0]["order"].due, js[0]["order"].priority))
    for order_jobs in orders:
        ready = order_jobs[0]["release"]  # when this order may start
        for j in order_jobs:
            if j["id"] in placed:
                ready = placed[j["id"]][1] + j["duration"]
                continue
            best = None
            for m in j["machines"]:
                gap = setup(m_last[m], j["product"]) if m_last[m] else 0
                for op_id in j["operators"]:
                    slot = earliest_slot(m, op_id, max(ready, j["release"], m_free[m] + gap, op_free[op_id]),
                                         j["duration"])
                    if slot and (best is None or slot[0] < best[1]):
                        best = (m, slot[0], op_id, slot[1])
            if best is None:
                raise ValueError(f"No machine/operator can ever run {j['order'].order_id} step {j['step']}")
            m, start, op_id, day = best
            placed[j["id"]] = best
            sequence[m].append(j["id"])
            ready = m_free[m] = op_free[op_id] = start + j["duration"]
            m_last[m] = j["product"]
    return placed, sequence


def _add_hint(model: cp_model.CpModel, jobs: list[dict], arcs_by_machine: dict, placed: dict,
              sequence: dict, late_vars: dict, window) -> None:
    """Give CP-SAT the greedy plan as a complete starting solution."""
    for j in jobs:
        m, start, op_id, day = placed[j["id"]]
        end = start + j["duration"]
        model.add_hint(j["start"], start)
        model.add_hint(j["end"], end)
        for machine, on_m in j["on"].items():
            model.add_hint(on_m, machine == m)
        for key, x in j["op"].items():
            model.add_hint(x, key == (op_id, day))
        model.add_hint(j["overtime"], max(0, end - window(op_id, day)[1]))
    for m, named in arcs_by_machine.items():
        seq = sequence[m]
        used = set(itertools.pairwise([None, *seq, None])) if seq else {(None, None)}
        for key, lit in named.items():
            model.add_hint(lit, key in used)
    for late, last_job, due in late_vars.values():
        end = placed[last_job["id"]][1] + last_job["duration"]
        model.add_hint(late, max(0, end - due))
