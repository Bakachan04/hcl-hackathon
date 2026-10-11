import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

try:
    from app.schemas import (
        Blocked,
        CheckResult,
        Job,
        KPIs,
        Operator,
        Order,
        Problem,
        RoutingStep,
    )
except ImportError:
    from .schemas import (
        Blocked,
        CheckResult,
        Job,
        KPIs,
        Operator,
        Order,
        Problem,
        RoutingStep,
    )

SKILL_LEVELS: Dict[str, int] = {
    "L1": 1,
    "L2": 2,
    "L3": 3,
}


def validate_plan(
    problem: Problem,
    jobs: List[Job],
    blocked: Optional[List[Blocked]] = None,
    fixed_jobs: Optional[List[Job]] = None,
) -> CheckResult:
    """Independently validate a production schedule against all constraints."""
    blocked = blocked or []
    fixed_jobs = fixed_jobs or []

    capacity_ok = True
    skill_ok = True
    changeover_ok = True
    precedence_ok = True
    eligibility_ok = True
    shift_ok = True
    wip_ok = True
    breakdown_ok = True
    violations: List[str] = []

    operators_map: Dict[str, Operator] = {op.operator_id: op for op in problem.operators}
    orders_map: Dict[str, Order] = {o.order_id: o for o in problem.orders}
    routing_map: Dict[Tuple[str, int], RoutingStep] = {
        (r.product, r.step): r for r in problem.routings
    }
    changeover_map: Dict[Tuple[str, str], int] = {
        (c.from_product, c.to_product): c.minutes for c in problem.changeovers
    }

    # Group jobs by machine, operator, and order
    jobs_by_machine: Dict[str, List[Job]] = {}
    jobs_by_operator: Dict[str, List[Job]] = {}
    jobs_by_order: Dict[str, List[Job]] = {}

    for job in jobs:
        jobs_by_machine.setdefault(job.machine, []).append(job)
        jobs_by_operator.setdefault(job.operator, []).append(job)
        jobs_by_order.setdefault(job.order_id, []).append(job)

    # 1. Capacity: No overlapping jobs on the same machine
    for machine, m_jobs in jobs_by_machine.items():
        sorted_jobs = sorted(m_jobs, key=lambda j: j.start)
        for i in range(len(sorted_jobs) - 1):
            j1 = sorted_jobs[i]
            j2 = sorted_jobs[i + 1]
            if j1.end > j2.start:
                capacity_ok = False
                violations.append(
                    f"Machine overlap on {machine}: job {j1.order_id} (step {j1.step}) "
                    f"[{j1.start.strftime('%Y-%m-%d %H:%M')}, {j1.end.strftime('%Y-%m-%d %H:%M')}] overlaps with "
                    f"job {j2.order_id} (step {j2.step}) [{j2.start.strftime('%Y-%m-%d %H:%M')}, {j2.end.strftime('%Y-%m-%d %H:%M')}]."
                )

    # 2. Eligibility & Duration: Machine allowed by routing step and scheduled duration matches formula
    for job in jobs:
        routing_step = routing_map.get((job.product, job.step))
        if routing_step is None:
            eligibility_ok = False
            violations.append(
                f"Missing routing definition for product {job.product} step {job.step} (job {job.order_id})."
            )
            continue

        if job.machine not in routing_step.machines:
            eligibility_ok = False
            violations.append(
                f"Machine eligibility violation: job {job.order_id} step {job.step} scheduled on machine "
                f"{job.machine}, which is not in allowed machines {routing_step.machines}."
            )

        order = orders_map.get(job.order_id)
        if order is not None:
            expected_minutes = math.ceil(order.qty * routing_step.minutes_per_unit)
            actual_minutes = round((job.end - job.start).total_seconds() / 60)
            if actual_minutes != expected_minutes:
                eligibility_ok = False
                violations.append(
                    f"Duration violation for job {job.order_id} step {job.step}: "
                    f"scheduled duration is {actual_minutes}m, expected ceil({order.qty} × {routing_step.minutes_per_unit}) = {expected_minutes}m."
                )

    # 3. Changeover: Directional product changeover gaps respected between consecutive jobs on same machine
    for machine, m_jobs in jobs_by_machine.items():
        sorted_jobs = sorted(m_jobs, key=lambda j: j.start)
        for i in range(len(sorted_jobs) - 1):
            j1 = sorted_jobs[i]
            j2 = sorted_jobs[i + 1]
            if j1.product != j2.product:
                required_gap = changeover_map.get((j1.product, j2.product), 0)
                actual_gap = (j2.start - j1.end).total_seconds() / 60
                if actual_gap < required_gap:
                    changeover_ok = False
                    violations.append(
                        f"Changeover violation on machine {machine}: transition from {j1.product} (job {j1.order_id}) "
                        f"to {j2.product} (job {j2.order_id}) requires {required_gap}m gap, but actual gap is {actual_gap:.1f}m."
                    )

    # 4. Precedence & Step Coverage: Consecutive steps ordered properly, every order step scheduled exactly once
    for order in problem.orders:
        order_routings = [r for r in problem.routings if r.product == order.product]
        order_routings.sort(key=lambda r: r.step)
        required_steps = [r.step for r in order_routings]

        order_jobs = jobs_by_order.get(order.order_id, [])
        scheduled_steps = [j.step for j in order_jobs]

        # Check step coverage
        if sorted(scheduled_steps) != required_steps:
            precedence_ok = False
            violations.append(
                f"Step coverage violation for order {order.order_id}: required steps {required_steps}, "
                f"scheduled steps {sorted(scheduled_steps)}."
            )

        # Check precedence between consecutive steps
        order_jobs_by_step = {j.step: j for j in order_jobs}
        for i in range(len(required_steps) - 1):
            step_curr = required_steps[i]
            step_next = required_steps[i + 1]
            if step_curr in order_jobs_by_step and step_next in order_jobs_by_step:
                j_curr = order_jobs_by_step[step_curr]
                j_next = order_jobs_by_step[step_next]
                if j_next.start < j_curr.end:
                    precedence_ok = False
                    violations.append(
                        f"Precedence violation for order {order.order_id}: step {step_next} starts at "
                        f"{j_next.start.strftime('%Y-%m-%d %H:%M')}, before step {step_curr} ends at {j_curr.end.strftime('%Y-%m-%d %H:%M')}."
                    )

    # 5. Skill: Operator skill meets job requirements
    for job in jobs:
        routing_step = routing_map.get((job.product, job.step))
        operator = operators_map.get(job.operator)
        if operator is None:
            skill_ok = False
            violations.append(
                f"Unknown operator {job.operator} assigned to job {job.order_id} step {job.step}."
            )
            continue

        if routing_step is not None:
            op_level = SKILL_LEVELS.get(operator.skill, 0)
            req_level = SKILL_LEVELS.get(routing_step.skill_required, 0)
            if op_level < req_level:
                skill_ok = False
                violations.append(
                    f"Skill violation: operator {operator.operator_id} (skill {operator.skill}) does not meet "
                    f"required {routing_step.skill_required} for job {job.order_id} step {job.step}."
                )

    # 6. Shift & Overtime: Job fits within operator shift + max 2h overtime, no operator overlap
    for operator_id, op_jobs in jobs_by_operator.items():
        operator = operators_map.get(operator_id)
        if operator is None:
            shift_ok = False
            violations.append(f"Unknown operator {operator_id} in shift evaluation.")
            continue

        # Overlapping jobs for operator
        sorted_op_jobs = sorted(op_jobs, key=lambda j: j.start)
        for i in range(len(sorted_op_jobs) - 1):
            j1 = sorted_op_jobs[i]
            j2 = sorted_op_jobs[i + 1]
            if j1.end > j2.start:
                shift_ok = False
                violations.append(
                    f"Operator overlap: operator {operator_id} assigned to overlapping jobs: "
                    f"{j1.order_id} (step {j1.step}) and {j2.order_id} (step {j2.step})."
                )

        # Shift bounds + max 2h overtime
        for job in op_jobs:
            shift_start_dt = datetime.combine(job.start.date(), operator.shift_start)
            shift_end_dt = datetime.combine(job.start.date(), operator.shift_end)
            max_allowed_end = shift_end_dt + timedelta(hours=2)

            if job.start < shift_start_dt:
                shift_ok = False
                violations.append(
                    f"Shift violation: job {job.order_id} step {job.step} starts at "
                    f"{job.start.strftime('%Y-%m-%d %H:%M')}, before operator {operator_id} shift start {shift_start_dt.strftime('%H:%M')}."
                )

            if job.end > max_allowed_end:
                shift_ok = False
                violations.append(
                    f"Overtime violation: job {job.order_id} step {job.step} ends at "
                    f"{job.end.strftime('%Y-%m-%d %H:%M')}, exceeding operator {operator_id} shift end "
                    f"({shift_end_dt.strftime('%H:%M')}) + max 2h overtime ({max_allowed_end.strftime('%H:%M')})."
                )

    # 7. WIP / Fixed jobs: fixed jobs remain exactly as required
    scheduled_jobs_by_key = {(j.order_id, j.step): j for j in jobs}

    for fj in fixed_jobs:
        matched = scheduled_jobs_by_key.get((fj.order_id, fj.step))
        if matched is None:
            wip_ok = False
            violations.append(
                f"Fixed job violation: required fixed job {fj.order_id} step {fj.step} is missing from plan."
            )
        else:
            if (
                matched.machine != fj.machine
                or matched.operator != fj.operator
                or matched.start != fj.start
                or matched.end != fj.end
            ):
                wip_ok = False
                violations.append(
                    f"Fixed job violation: job {fj.order_id} step {fj.step} modified from fixed values "
                    f"(machine: {matched.machine} vs {fj.machine}, operator: {matched.operator} vs {fj.operator}, "
                    f"start: {matched.start} vs {fj.start}, end: {matched.end} vs {fj.end})."
                )

    for order in problem.orders:
        if order.movable is False and order.wip_step is not None:
            matched = scheduled_jobs_by_key.get((order.order_id, order.wip_step))
            if matched is None:
                wip_ok = False
                violations.append(
                    f"WIP immovability violation: order {order.order_id} step {order.wip_step} is not scheduled."
                )
            else:
                if order.wip_machine and matched.machine != order.wip_machine:
                    wip_ok = False
                    violations.append(
                        f"WIP violation for order {order.order_id} step {order.wip_step}: machine {matched.machine} != fixed {order.wip_machine}."
                    )
                if order.wip_operator and matched.operator != order.wip_operator:
                    wip_ok = False
                    violations.append(
                        f"WIP violation for order {order.order_id} step {order.wip_step}: operator {matched.operator} != fixed {order.wip_operator}."
                    )
                if order.wip_start and matched.start != order.wip_start:
                    wip_ok = False
                    violations.append(
                        f"WIP violation for order {order.order_id} step {order.wip_step}: start {matched.start} != fixed {order.wip_start}."
                    )
                if order.wip_end and matched.end != order.wip_end:
                    wip_ok = False
                    violations.append(
                        f"WIP violation for order {order.order_id} step {order.wip_step}: end {matched.end} != fixed {order.wip_end}."
                    )

    # 8. Breakdown: No job overlaps a Blocked window on its machine
    for b in blocked:
        m_jobs = jobs_by_machine.get(b.machine, [])
        for job in m_jobs:
            if max(job.start, b.start) < min(job.end, b.end):
                breakdown_ok = False
                violations.append(
                    f"Breakdown violation on machine {b.machine}: job {job.order_id} step {job.step} "
                    f"[{job.start.strftime('%Y-%m-%d %H:%M')}, {job.end.strftime('%Y-%m-%d %H:%M')}] overlaps "
                    f"breakdown window [{b.start.strftime('%Y-%m-%d %H:%M')}, {b.end.strftime('%Y-%m-%d %H:%M')}]."
                )

    return CheckResult(
        capacity_ok=capacity_ok,
        skill_ok=skill_ok,
        changeover_ok=changeover_ok,
        precedence_ok=precedence_ok,
        eligibility_ok=eligibility_ok,
        shift_ok=shift_ok,
        wip_ok=wip_ok,
        breakdown_ok=breakdown_ok,
        violations=violations,
    )


def compute_kpis(
    problem: Problem,
    jobs: List[Job],
    old_plan: Optional[List[Job]] = None,
) -> KPIs:
    """Calculate key performance indicators for a production schedule."""
    operators_map: Dict[str, Operator] = {op.operator_id: op for op in problem.operators}

    # Group jobs by order and by machine
    jobs_by_order: Dict[str, List[Job]] = {}
    jobs_by_machine: Dict[str, List[Job]] = {}

    for job in jobs:
        jobs_by_order.setdefault(job.order_id, []).append(job)
        jobs_by_machine.setdefault(job.machine, []).append(job)

    # 1. Late orders and Total lateness (hours)
    late_orders = 0
    total_lateness_h = 0.0

    for order in problem.orders:
        order_jobs = jobs_by_order.get(order.order_id, [])
        if order_jobs:
            completion = max(j.end for j in order_jobs)
            if completion > order.due:
                late_orders += 1
                lateness_seconds = (completion - order.due).total_seconds()
                total_lateness_h += lateness_seconds / 3600.0

    # 2. Overtime (hours)
    total_overtime_minutes = 0.0
    for job in jobs:
        operator = operators_map.get(job.operator)
        if operator is not None:
            shift_end_dt = datetime.combine(job.start.date(), operator.shift_end)
            if job.end > shift_end_dt:
                overtime_start = max(job.start, shift_end_dt)
                overtime_mins = (job.end - overtime_start).total_seconds() / 60.0
                total_overtime_minutes += max(0.0, overtime_mins)

    overtime_h = total_overtime_minutes / 60.0

    # 3. Changeovers count
    changeovers_count = 0
    for machine, m_jobs in jobs_by_machine.items():
        sorted_jobs = sorted(m_jobs, key=lambda j: j.start)
        for i in range(len(sorted_jobs) - 1):
            if sorted_jobs[i].product != sorted_jobs[i + 1].product:
                changeovers_count += 1

    # 4. Moved jobs
    moved_jobs_count = 0
    if old_plan:
        old_jobs_map = {(j.order_id, j.step): j for j in old_plan}
        for j in jobs:
            old_j = old_jobs_map.get((j.order_id, j.step))
            if old_j is not None:
                if j.machine != old_j.machine or j.start != old_j.start:
                    moved_jobs_count += 1

    return KPIs(
        late_orders=late_orders,
        total_lateness_h=round(total_lateness_h, 2),
        overtime_h=round(overtime_h, 2),
        changeovers=changeovers_count,
        moved_jobs=moved_jobs_count,
    )

