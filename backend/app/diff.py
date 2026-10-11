"""diff_plans: what moved between two plans, and why. Owner: Adarsh.

The reason for every move is decided here, in code, from the plan data. The LLM only
rephrases these reasons; it never invents them.
"""

from app.schemas import Change, Disruption, Job


def _at(job: Job) -> str:
    return f"{job.machine} {job.start:%Y-%m-%d %H:%M}"


def diff_plans(old: list[Job], new: list[Job], events: list[Disruption]) -> list[Change]:
    old_by_key = {(j.order_id, j.step): j for j in old}
    new_by_key = {(j.order_id, j.step): j for j in new}
    breakdowns = [e for e in events if e.kind == "breakdown"]
    rush_ids = {e.target for e in events if e.kind == "rush_order"}

    changes = []
    for key, nj in sorted(new_by_key.items()):
        oj = old_by_key.get(key)
        if oj is None:
            changes.append(Change(order_id=nj.order_id, step=nj.step, from_="(new)", to=_at(nj),
                                  reason_code="new_order",
                                  facts={"rush_order": nj.order_id in rush_ids}))
            continue
        if oj.machine == nj.machine and oj.start == nj.start:
            continue

        hit = next((b for b in breakdowns if b.target == oj.machine and oj.end > b.at), None)
        prev = old_by_key.get((nj.order_id, nj.step - 1))
        prev_new = new_by_key.get((nj.order_id, nj.step - 1))
        if hit:
            code, facts = "machine_down", {"machine": hit.target, "down_from": f"{hit.at:%Y-%m-%d %H:%M}",
                                           "down_hours": hit.duration_h}
        elif prev and prev_new and prev_new.end > prev.end:
            code, facts = "precedence", {"previous_step_now_ends": f"{prev_new.end:%Y-%m-%d %H:%M}"}
        elif rush_ids and nj.start > oj.start:
            code, facts = "displaced_by_rush", {"rush_orders": sorted(rush_ids)}
        else:
            code, facts = "rebalanced", {}
        changes.append(Change(order_id=nj.order_id, step=nj.step, from_=_at(oj), to=_at(nj),
                              reason_code=code, facts=facts))
    return changes
