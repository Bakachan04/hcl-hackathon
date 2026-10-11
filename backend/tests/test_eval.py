import json
from datetime import datetime
from pathlib import Path

from eval.run_eval import (
    EVAL_DIR,
    case_disruptions,
    check_case,
    request_body,
    summarize,
)
from scripts.generate_data import generate

JOB = {"order_id": "O-1", "step": 1, "product": "P1", "machine": "CNC-3", "operator": "OP-01",
       "start": "2026-10-12 09:00", "end": "2026-10-12 11:00"}


def test_cases_meet_guide_minimums():
    cases = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    assert len(cases) >= 20
    assert len({c["id"] for c in cases}) == len(cases)
    broken = {e for c in by_cat["disruption"] for e in c.get("events", ["?"])}
    assert len(by_cat["disruption"]) >= 3 and len(broken) >= 3
    for cat in ("rush", "infeasible", "tradeoff", "llm_plan_attempt"):
        assert len(by_cat[cat]) >= 2, cat
    weights = {json.dumps(c.get("weights")) for c in by_cat["tradeoff"]}
    assert len(weights) >= 2


def test_disruption_file_rows_become_request_body(tmp_path: Path):
    generate(42, tmp_path)
    events = case_disruptions({"id": "X", "disruption_file": "disruption.csv", "events": ["D-1"]}, tmp_path)
    body = request_body({"request": "re-plan", "weights": {"late": 1}}, events)
    assert body["disruption"] == [{"event_id": "D-1", "kind": "breakdown", "at": "2026-10-12 10:00",
                                   "target": "CNC-3", "duration_h": 6.0}]
    assert body["weights"] == {"late": 1}


def test_check_case_catches_machine_clash_and_wrong_type():
    from eval.run_eval import _jobs
    resp = {"answer_type": "plan", "plan": [JOB]}
    expected = {"answer_type": "replan",
                "machine_free": [{"machine": "CNC-3", "start": "2026-10-12 10:00", "end": "2026-10-12 16:00"}],
                "orders_late": ["O-1"]}
    fails = check_case(expected, resp, _jobs(resp), {"O-1": datetime(2026, 10, 12, 18)}, plan_ok=True)
    assert len(fails) == 3


def test_check_case_passes_good_refusal():
    assert check_case({"answer_type": "refused", "plan_empty": True},
                      {"answer_type": "refused", "plan": []}, [], {}, None) == []


def test_summary_counts():
    row = {"status": 200, "jobs": 3, "category": "rush", "plan_ok": True, "passed": True, "fails": [],
           "late_orders": 1, "total_lateness_h": 2.0, "overtime_h": 0, "changeovers": 4, "moved_jobs": 2,
           "latency_s": 1.0, "solve_s": 0.5, "faithful": True, "llm_calls": 1, "tokens": 100}
    s = summarize([row, {**row, "plan_ok": False, "passed": False, "fails": ["plan failed the validator"]}])
    assert s["plan_validity"] == 0.5 and s["answer_type_accuracy"] == 1.0 and s["tokens"] == 200
