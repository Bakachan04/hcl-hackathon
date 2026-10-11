"""Pre-analysis data checks (guide 4.5). Owner: Lavanya.

run_checks(problem) returns one {"check", "passed", "detail"} dict per check. The first six
are the guide 4.5 checks; the rest catch data the solver could never schedule.
"""

import re
from collections import defaultdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from app.schemas import Problem, skill_rank

# Data card table "| <key> | <rows> |" lines (see docs/data_card.md, "Row counts").
COUNT_KEYS = ("orders", "routings", "changeovers", "operators")
_COUNT_LINE = re.compile(r"^\|\s*`?(" + "|".join(COUNT_KEYS) + r")`?\s*\|\s*(\d+)\s*\|", re.MULTILINE)


def _result(check: str, problems: list[str], ok_detail: str) -> dict:
    if problems:
        shown = problems[:8] + ([f"... {len(problems) - 8} more"] if len(problems) > 8 else [])
        return {"check": check, "passed": False, "detail": "; ".join(shown)}
    return {"check": check, "passed": True, "detail": ok_detail}


def counts_from_data_card(path: Path) -> dict[str, int]:
    """Expected row counts from the data card's "Row counts" table."""
    return {k: int(v) for k, v in _COUNT_LINE.findall(Path(path).read_text(encoding="utf-8"))}


def problem_counts(problem: Problem) -> dict[str, int]:
    return {"orders": len(problem.orders), "routings": len(problem.routings),
            "changeovers": len(problem.changeovers), "operators": len(problem.operators)}


def _shift_window(day: datetime, op) -> tuple[datetime, datetime]:
    start = datetime.combine(day.date(), op.shift_start)
    end = datetime.combine(day.date(), op.shift_end)
    return start, end


def run_checks(problem: Problem, expected_counts: dict[str, int] | None = None) -> list[dict]:
    steps_by_product = defaultdict(list)
    for s in problem.routings:
        steps_by_product[s.product].append(s)
    used = sorted({o.product for o in problem.orders})
    results = []

    # 1. Every order's product has a routing.
    bad = [f"{o.order_id} ({o.product})" for o in problem.orders if o.product not in steps_by_product]
    results.append(_result("order_products_have_routing", bad,
                           f"{len(problem.orders)} orders, {len(used)} products, all routed"))

    # 2. Every routing step has at least one capable machine (and steps are 1..n).
    bad = [f"{s.product} step {s.step}" for s in problem.routings if not s.machines]
    for product, steps in steps_by_product.items():
        numbers = sorted(s.step for s in steps)
        if numbers != list(range(1, len(numbers) + 1)):
            bad.append(f"{product} steps {numbers} are not 1..{len(numbers)}")
    results.append(_result("routing_steps_have_machine", bad,
                           f"{len(problem.routings)} steps on {len(problem.machines)} machines"))

    # 3. Due dates are after the planning start.
    bad = [f"{o.order_id} due {o.due:%Y-%m-%d %H:%M}" for o in problem.orders if o.due <= problem.plan_start]
    results.append(_result("due_after_plan_start", bad,
                           f"all due after {problem.plan_start:%Y-%m-%d %H:%M}"))

    # 4. Changeover table covers every ordered pair of products in use.
    have = {(c.from_product, c.to_product) for c in problem.changeovers}
    bad = [f"{a}->{b}" for a in used for b in used if a != b and (a, b) not in have]
    n_pairs = len(used) * (len(used) - 1)
    results.append(_result("changeovers_cover_product_pairs", bad, f"{n_pairs}/{n_pairs} pairs covered"))

    # 5. Roster hours are not negative or overlapping (per operator, on any day).
    bad = []
    by_op = defaultdict(list)
    for op in problem.operators:
        start, end = _shift_window(problem.plan_start, op)
        if end <= start:
            bad.append(f"{op.operator_id} shift {op.shift} ends before it starts")
        by_op[op.operator_id].append((start, end))
    for op_id, windows in by_op.items():
        windows.sort()
        for (s1, e1), (s2, _) in pairwise(windows):
            if s2 < e1:
                bad.append(f"{op_id} has overlapping shifts")
    results.append(_result("roster_hours_valid", bad, f"{len(problem.operators)} operators, no overlaps"))

    # 6. Row counts match the data card.
    if expected_counts is None:
        results.append({"check": "row_counts_match_data_card", "passed": True,
                        "detail": "skipped: no data card given"})
    else:
        actual = problem_counts(problem)
        bad = [f"{k}: data card {expected_counts[k]}, loaded {actual[k]}"
               for k in COUNT_KEYS if k in expected_counts and expected_counts[k] != actual[k]]
        missing = [k for k in COUNT_KEYS if k not in expected_counts]
        bad += [f"{k}: not in data card" for k in missing]
        results.append(_result("row_counts_match_data_card", bad,
                               ", ".join(f"{k}={v}" for k, v in actual.items())))

    # 7. Every skill a step needs is held by at least one operator.
    levels = [skill_rank(op.skill) for op in problem.operators]
    bad = [f"{s.product} step {s.step} needs {s.skill_required}" for s in problem.routings
           if not any(lv >= skill_rank(s.skill_required) for lv in levels)]
    results.append(_result("skills_have_operator", bad, "every required skill is covered"))

    # 8. Work in progress points at a real machine/operator that can run that step.
    ops = {op.operator_id: op for op in problem.operators}
    bad = []
    n_wip = 0
    for o in problem.orders:
        if o.wip_step is None:
            continue
        n_wip += 1
        step = next((s for s in steps_by_product.get(o.product, []) if s.step == o.wip_step), None)
        if step is None:
            bad.append(f"{o.order_id}: no step {o.wip_step} for {o.product}")
            continue
        if o.wip_machine not in step.machines:
            bad.append(f"{o.order_id}: {o.wip_machine} cannot run {o.product} step {o.wip_step}")
        op = ops.get(o.wip_operator) if o.wip_operator else None
        if o.wip_operator and op is None:
            bad.append(f"{o.order_id}: unknown operator {o.wip_operator}")
        elif op and skill_rank(op.skill) < skill_rank(step.skill_required):
            bad.append(f"{o.order_id}: {op.operator_id} ({op.skill}) below {step.skill_required}")
    results.append(_result("wip_consistent", bad, f"{n_wip} WIP jobs consistent"))

    return results


def all_passed(results: list[dict]) -> bool:
    return all(r["passed"] for r in results)

