"""LangGraph pipeline behind POST /analyze. Owner: Adarsh.

  parse_request -> solve_schedule -> validate_plan -> diff_plans -> explain -> respond
        |                                                                       ^
        +---- refused / clarification_needed / explanation ---------------------+

One fixed pipeline, not free-roaming agents: the request is routed by keyword rules,
the plan comes from the CP-SAT solver tool, the checker validates it, and the LLM only
explains facts the tools returned. Every node records a step in the trace.
"""

import operator
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from app import config, store
from app.checker import validate_plan
from app.diff import diff_plans
from app.explain import explain
from app.loader import load_disruptions, load_problem
from app.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    Blocked,
    Disruption,
    Order,
    Weights,
)
from app.solver import solve_schedule

ASSUMPTIONS = [
    "Shifts: A 06:00-14:00, B 14:00-22:00, every day; up to 2 h overtime after shift end.",
    "A job must start inside the regular shift; overtime only finishes a running job.",
    "Skill levels L1 < L2 < L3; a higher level can do lower-level work.",
    "Lateness cost is multiplied by priority (P1 x3, P2 x2, P3 x1) and x2 for key customers.",
    ("On a replan, work started before the disruption stays as planned; a job running on the "
    "broken machine restarts from scratch after the repair or on another machine."),
    "Moving a job away from the old plan costs 1 weight per hour moved and per machine change.",
]
REFUSE = re.compile(r"\b(skip|ignore|bypass|disable|without|break)\b.*\b(skill|changeover|shift|rule|check|validat)",
                    re.IGNORECASE)
REPLAN = re.compile(r"re-?plan|break ?down|\bdown\b|rush|disruption", re.IGNORECASE)
ORDER_ID = re.compile(r"\b([A-Z]-?\d{2,})\b")
MACHINE_ID = re.compile(r"\b([A-Z]{2,}-\d+)\b")

# Changes of the most recent replan, so "Why did order X move?" can be answered.
_last_changes: dict[str, dict] = {}


class State(TypedDict, total=False):
    request: AnalyzeRequest
    run_id: str
    answer_type: str
    message: str
    problem: Any
    events: list
    old_plan: list
    result: Any
    blocked: list
    fixed: list
    check: Any
    changes: list
    explanation: str
    llm: dict
    steps: Annotated[list, operator.add]


def _step(agent: str, tool: str, output: dict | None = None, inp: dict | None = None) -> dict:
    return {k: v for k, v in {"agent": agent, "tool": tool, "input": inp, "output": output}.items() if v is not None}


# ---------------------------------------------------------------- nodes

def parse_request(state: State) -> dict:
    req = state["request"]
    text = req.request
    problem = load_problem()
    if not problem.orders:
        return {"answer_type": "clarification_needed", "problem": problem,
                "message": "No data loaded. Load the CSV files first (scripts/load_data.py or POST /ingest).",
                "steps": [_step("planner", "parse_request", {"route": "clarification_needed"})]}
    if REFUSE.search(text):
        return {"answer_type": "refused", "problem": problem,
                "message": "Refused: every plan must respect skills, shifts, changeovers and machine "
                           "capacity. The plan checker validates all rules before a plan is shown.",
                "steps": [_step("planner", "parse_request", {"route": "refused"})]}
    if text.lower().startswith("why") and (m := ORDER_ID.search(text)):
        return {"answer_type": "explanation", "problem": problem, "message": m.group(1),
                "steps": [_step("planner", "parse_request", {"route": "explanation", "order": m.group(1)})]}

    events = list(req.disruption or [])
    unknown = [t for t in MACHINE_ID.findall(text) if t not in problem.machines and not ORDER_ID.fullmatch(t)]
    if not events and unknown:
        return {"answer_type": "clarification_needed", "problem": problem,
                "message": f"Unknown machine {unknown[0]}. Known machines: {', '.join(problem.machines)}.",
                "steps": [_step("planner", "parse_request", {"route": "clarification_needed"})]}
    if not events and REPLAN.search(text):
        events = _events_from_text(text, problem) or load_disruptions()
        if not events:
            return {"answer_type": "clarification_needed", "problem": problem,
                    "message": "Which machine is down, from when and for how long (or which rush order)?",
                    "steps": [_step("planner", "parse_request", {"route": "clarification_needed"})]}
    for e in events:
        if e.kind == "breakdown" and e.target not in problem.machines:
            return {"answer_type": "clarification_needed", "problem": problem,
                    "message": f"Unknown machine {e.target}. Known machines: {', '.join(problem.machines)}.",
                    "steps": [_step("planner", "parse_request", {"route": "clarification_needed"})]}
        if e.kind == "rush_order" and e.product not in {r.product for r in problem.routings}:
            return {"answer_type": "clarification_needed", "problem": problem,
                    "message": f"Rush order {e.target} has unknown product {e.product}.",
                    "steps": [_step("planner", "parse_request", {"route": "clarification_needed"})]}
    route = "replan" if events else "plan"
    return {"answer_type": route, "problem": problem, "events": events,
            "steps": [_step("planner", "parse_request", {"route": route, "events": len(events)})]}


def _events_from_text(text: str, problem) -> list[Disruption]:
    """'CNC-3 is down for 6 hours [at 10:00]' -> a breakdown event."""
    machine = next((m for m in problem.machines if m.lower() in text.lower()), None)
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hours?)\b", text, re.IGNORECASE)
    if not (machine and hours):
        return []
    clock = re.search(r"\b(?:at|from)\s+(\d{1,2}):(\d{2})", text)
    at = problem.plan_start
    if clock:
        at = at.replace(hour=int(clock.group(1)), minute=int(clock.group(2)))
    return [Disruption(event_id="TEXT-1", kind="breakdown", at=at, target=machine, duration_h=float(hours.group(1)))]


def solve(state: State) -> dict:
    req, problem = state["request"], state["problem"]
    weights = req.weights or Weights()
    allow_ot = not req.avoid_overtime
    if state["answer_type"] == "plan":
        result = solve_schedule(problem, weights, allow_overtime=allow_ot)
        return {"result": result, "old_plan": [], "blocked": [], "fixed": [],
                "steps": [_step("solver", "solve_schedule", {"status": result.status, "solve_s": result.solve_s},
                                {"weights": weights.model_dump()})]}

    # Replan: start from the latest stored plan (or build the baseline first).
    steps = []
    old_plan = store.latest_plan()
    if not old_plan:
        base = solve_schedule(problem, weights, allow_overtime=allow_ot)
        old_plan = base.jobs
        steps.append(_step("solver", "solve_schedule", {"status": base.status, "purpose": "baseline"}))
    events = state["events"]
    t = min(e.at for e in events)
    blocked = [Blocked(machine=e.target, start=e.at, end=e.at + timedelta(hours=e.duration_h or 0))
               for e in events if e.kind == "breakdown"]
    broken = {b.machine for b in blocked}
    # Done or running at time t stays as is, except a job running on a machine that breaks.
    fixed = [j for j in old_plan if j.start < t and not (j.machine in broken and j.end > t)]
    not_before = {}
    for e in events:
        if e.kind == "rush_order":
            problem.orders.append(Order(order_id=e.target, product=e.product, qty=e.qty, due=e.due,
                                        priority=e.priority or 1, customer=e.customer or "rush"))
            not_before[e.target] = e.at
    steps.append(_step("planner", "load_plan_state",
                       {"jobs_in_old_plan": len(old_plan), "fixed_jobs": len(fixed), "disruption_at": str(t)}))
    result = solve_schedule(problem, weights, fixed_jobs=fixed, blocked=blocked, not_before=not_before,
                            earliest_start=t, old_plan=old_plan, allow_overtime=allow_ot)
    steps.append(_step("solver", "solve_schedule", {"status": result.status, "solve_s": result.solve_s},
                       {"weights": weights.model_dump(), "blocked": [b.model_dump(mode="json") for b in blocked]}))
    return {"result": result, "old_plan": old_plan, "blocked": blocked, "fixed": fixed, "steps": steps}


def check(state: State) -> dict:
    r = state["result"]
    c = validate_plan(state["problem"], r.jobs, state["blocked"], state["fixed"]) if r.jobs else None
    out = {k: v for k, v in c.model_dump().items() if k != "violations"} if c else {"status": r.status}
    return {"check": c, "steps": [_step("checker", "validate_plan", out)]}


def diff(state: State) -> dict:
    changes = diff_plans(state["old_plan"], state["result"].jobs, state.get("events", [])) \
        if state["old_plan"] and state["result"].jobs else []
    return {"changes": changes, "steps": [_step("planner", "diff_plans", {"moved_jobs": len(changes)})]}


def explain_node(state: State) -> dict:
    if state["answer_type"] == "explanation":
        info = _last_changes.get(state["message"])
        facts = {"order_id": state["message"], "change": info} if info else {"order_id": state["message"],
                                                                                   "change": "not moved in the last replan"}
    else:
        r = state["result"]
        facts = {"answer_type": state["answer_type"], "status": r.status,
                 "kpis": r.kpis.model_dump() if r.kpis else None,
                 "validator_all_ok": state["check"].all_ok if state["check"] else False,
                 "changes": [c.model_dump() for c in state["changes"][:15]],
                 "moved_jobs": len(state["changes"])}
    text, usage = explain(facts)
    # A headline built in code from tool results is always shown; the LLM text is added only
    # when a real LLM answered (mock mode returns a generic template).
    headline = _headline(state)
    full = f"{headline} {text}" if usage.get("llm_calls", 0) else headline
    return {"explanation": full, "llm": usage,
            "steps": [_step("explainer", "explain", {"fact_check_passed": usage.get("fact_check_passed"),
                                                     "llm_calls": usage.get("llm_calls", 0)})]}


REASONS = {
    "machine_down": "its machine is broken down",
    "displaced_by_rush": "a rush order took its slot",
    "precedence": "its previous step now finishes later",
    "rebalanced": "the solver rebalanced the work to reduce lateness and changeovers",
    "new_order": "it is a new order",
}


def _headline(state: State) -> str:
    if state["answer_type"] == "explanation":
        info = _last_changes.get(state["message"])
        if not info:
            return f"Order {state['message']} did not move in the last replan."
        ch = info["change"]
        return f"Order {ch.order_id} step {ch.step} moved from {ch.from_} to {ch.to} because {REASONS[ch.reason_code]}."
    r, k = state["result"], state["result"].kpis
    if not k:
        return f"No valid plan found (solver status {r.status})."
    rules = "all rules pass the plan checker" if state["check"] and state["check"].all_ok else "the plan breaks a rule"
    head = (f"{len(state['problem'].orders)} orders planned: {k.late_orders} late ({k.total_lateness_h} h total), "
            f"{k.overtime_h} h overtime, {k.changeovers} changeovers; {rules}.")
    if state["answer_type"] == "replan":
        events = "; ".join(f"{e.target} down from {e.at:%H:%M} for {e.duration_h} h" if e.kind == "breakdown"
                           else f"rush order {e.target} arrives {e.at:%H:%M}" for e in state["events"])
        head = f"Disruption: {events}. {len(state['changes'])} jobs moved. " + head
    return head


# ---------------------------------------------------------------- graph

def _route(state: State) -> str:
    if state["answer_type"] in ("plan", "replan"):
        return "solve"
    return "explain" if state["answer_type"] == "explanation" else END


def _build():
    g = StateGraph(State)
    g.add_node("parse_request", parse_request)
    g.add_node("solve", solve)
    g.add_node("check", check)
    g.add_node("diff", diff)
    g.add_node("explain", explain_node)
    g.set_entry_point("parse_request")
    g.add_conditional_edges("parse_request", _route, {"solve": "solve", "explain": "explain", END: END})
    g.add_edge("solve", "check")
    g.add_edge("check", "diff")
    g.add_edge("diff", "explain")
    g.add_edge("explain", END)
    return g.compile()


PIPELINE = _build()


def run(req: AnalyzeRequest) -> AnalyzeResponse:
    t0 = time.perf_counter()
    run_id = "pl-" + uuid.uuid4().hex[:6]
    state = PIPELINE.invoke({"request": req, "run_id": run_id, "steps": []})
    answer = state["answer_type"]
    r, c = state.get("result"), state.get("check")
    limitations = []

    if answer in ("refused", "clarification_needed"):
        resp = AnalyzeResponse(run_id=run_id, answer_type=answer, summary=state["message"])
    elif answer == "explanation":
        resp = AnalyzeResponse(run_id=run_id, answer_type=answer, summary=state["explanation"],
                               changes=[_last_changes[state["message"]]["change"]]
                               if state["message"] in _last_changes else [])
    elif not r.jobs or not (c and c.all_ok):
        # Never show a plan that breaks a rule.
        resp = AnalyzeResponse(run_id=run_id, answer_type="infeasible", validator=c,
                               summary=f"No valid plan found (solver status {r.status}).",
                               limitations=(c.violations[:10] if c else []))
    else:
        moved = {(ch.order_id, ch.step) for ch in state["changes"]}
        plan = [j.model_copy(update={"changed": (j.order_id, j.step) in moved}) for j in r.jobs]
        if r.kpis.late_orders:
            done = {}
            for j in r.jobs:
                done[j.order_id] = max(done.get(j.order_id, j.end), j.end)
            due = {o.order_id: o.due for o in state["problem"].orders}
            late = [o for o in done if done[o] > due[o]]
            limitations.append(f"Late in this plan: {', '.join(sorted(late))}.")
        if r.status == "GREEDY_FALLBACK":
            limitations.append("Solver found no better plan in time; showing the valid greedy plan.")
        resp = AnalyzeResponse(run_id=run_id, answer_type=answer, summary=state["explanation"], plan=plan,
                               kpis=r.kpis.model_copy(update={"moved_jobs": len(state["changes"])}),
                               changes=state["changes"], validator=c,
                               assumptions=[f"Weights: {(state['request'].weights or Weights()).model_dump()}",
                                            *ASSUMPTIONS],
                               limitations=limitations)
        store.save_plan(run_id, r.jobs)
        if answer == "replan":
            _last_changes.clear()
            for ch in state["changes"]:
                _last_changes[ch.order_id] = {"change": ch, "run_id": run_id}

    llm = state.get("llm") or {}
    store.save_trace(run_id, {
        "run_id": run_id, "request": state["request"].request, "answer_type": resp.answer_type,
        "steps": state["steps"], "llm_calls": llm.get("llm_calls", 0), "tokens": llm.get("tokens", 0),
        "latency_s": round(time.perf_counter() - t0, 3), "llm_provider": config.LLM_PROVIDER,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    return resp
