"""Evaluation runner. Owner: Lavanya.

Runs every case in eval/cases.json against POST /analyze, checks the expected result
(exact match on answer_type + rule checks on the plan) and reports the guide section 7
metrics. Results are saved per configuration so two runs can be compared.

    python eval/run_eval.py --label baseline                  # in-process (no server needed)
    python eval/run_eval.py --label flash-lite --url http://localhost:8000
    python eval/run_eval.py --compare eval/results/a.json eval/results/b.json

Switch configurations (model, solver settings) in backend/.env between runs.
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app import config, loader
from app.schemas import TIME_FMT, Blocked, Disruption, Job, Order

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"


# ---------- Client: in-process TestClient or a running server ----------

class Client:
    def __init__(self, url: str | None):
        if url:
            import httpx
            self._http = httpx.Client(base_url=url, timeout=300)
        else:
            from fastapi.testclient import TestClient

            from app.main import app
            self._http = TestClient(app)

    def analyze(self, body: dict) -> tuple[int, dict]:
        r = self._http.post("/analyze", json=body)
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})

    def trace(self, run_id: str) -> dict:
        r = self._http.get(f"/trace/{run_id}")
        return r.json() if r.status_code == 200 else {}


# ---------- Case inputs ----------

def case_disruptions(case: dict, data_dir: Path) -> list[Disruption]:
    if "disruption" in case:
        return [Disruption(**e) for e in case["disruption"]]
    if "disruption_file" not in case:
        return []
    df, result = loader.check_table("disruption", data_dir / case["disruption_file"])
    if result.status == "failed":
        raise RuntimeError(f"{case['id']}: cannot read {case['disruption_file']}: {result.errors}")
    events = [loader.PARSERS["disruption"](row)[0] for row in df.to_dict("records")]
    wanted = case.get("events")
    return [e for e in events if wanted is None or e.event_id in wanted]


def request_body(case: dict, events: list[Disruption]) -> dict:
    body = {"request": case["request"]}
    if events:
        body["disruption"] = [json.loads(e.model_dump_json(exclude_none=True)) for e in events]
        for d in body["disruption"]:  # contract time format
            for k in ("at", "due"):
                if k in d:
                    d[k] = datetime.fromisoformat(d[k]).strftime(TIME_FMT)
    if case.get("weights"):
        body["weights"] = case["weights"]
    return body


# ---------- Expectation checks ----------

def _dt(s: str) -> datetime:
    return datetime.strptime(s, TIME_FMT)


def _jobs(resp: dict) -> list[Job]:
    jobs = []
    for j in resp.get("plan") or []:
        j = dict(j)
        j.setdefault("product", "")
        jobs.append(Job(**j))
    return jobs


def order_completion(jobs: list[Job]) -> dict[str, datetime]:
    done: dict[str, datetime] = {}
    for j in jobs:
        done[j.order_id] = max(done.get(j.order_id, j.end), j.end)
    return done


def check_case(expected: dict, resp: dict, jobs: list[Job], due: dict[str, datetime],
               plan_ok: bool | None) -> list[str]:
    """Return the list of failed expectations (empty = case passed)."""
    fails = []
    want = expected.get("answer_type")
    allowed = [want] if isinstance(want, str) else (want or [])
    if allowed and resp.get("answer_type") not in allowed:
        fails.append(f"answer_type {resp.get('answer_type')!r} not in {allowed}")
    if expected.get("plan_valid") and jobs and plan_ok is False:
        fails.append("plan failed the validator")
    if expected.get("plan_empty") and jobs:
        fails.append(f"expected no plan, got {len(jobs)} jobs")

    by_key = {(j.order_id, j.step): j for j in jobs}
    for u in expected.get("unchanged_jobs", []) if jobs else []:
        j = by_key.get((u["order_id"], u["step"]))
        if not j or (j.machine, j.start, j.end) != (u["machine"], _dt(u["start"]), _dt(u["end"])):
            fails.append(f"WIP {u['order_id']} step {u['step']} moved")
    for w in expected.get("machine_free", []) if jobs else []:
        s, e = _dt(w["start"]), _dt(w["end"])
        clash = [j.order_id for j in jobs if j.machine == w["machine"] and j.start < e and j.end > s]
        if clash:
            fails.append(f"{w['machine']} used while down by {clash}")
    for n in expected.get("job_not_on", []):
        j = by_key.get((n["order_id"], n["step"]))
        if j and j.machine == n["machine"]:
            fails.append(f"{n['order_id']} step {n['step']} placed on {n['machine']}")

    done = order_completion(jobs)
    for oid in expected.get("includes_orders", []):
        if oid not in done:
            fails.append(f"{oid} missing from plan")
    for oid in expected.get("orders_late", []):
        if oid in done and oid in due and done[oid] <= due[oid]:
            fails.append(f"{oid} expected late but on time")
    for oid in expected.get("orders_on_time", []):
        if oid in done and oid in due and done[oid] > due[oid]:
            fails.append(f"{oid} expected on time but late")
    summary = (resp.get("summary") or "").lower()
    for word in expected.get("summary_mentions", []):
        if word.lower() not in summary:
            fails.append(f"summary does not mention {word}")
    return fails


def independent_check(problem, jobs: list[Job], events: list[Disruption]):
    """Re-check the plan with our own checker (Ridhi's), if it is available."""
    try:
        from app.checker import validate_plan
    except ImportError:
        return None
    rush = [Order(order_id=e.target, product=e.product, qty=e.qty, due=e.due, priority=e.priority or 1,
                  customer=e.customer or "rush") for e in events if e.kind == "rush_order"]
    blocked = [Blocked(machine=e.target, start=e.at, end=e.at + timedelta(hours=e.duration_h))
               for e in events if e.kind == "breakdown"]
    fixed = [Job(order_id=o.order_id, step=o.wip_step, product=o.product, machine=o.wip_machine,
                 operator=o.wip_operator or "", start=o.wip_start, end=o.wip_end)
             for o in problem.orders if o.wip_step is not None and not o.movable]
    p = problem.model_copy(update={"orders": problem.orders + rush})
    try:
        return validate_plan(p, jobs, blocked=blocked, fixed_jobs=fixed).all_ok
    except Exception:  # noqa: BLE001 - a checker crash should not stop the evaluation
        return None


def _trace_facts(trace: dict) -> dict:
    steps = trace.get("steps") or []
    solve = next((s for s in steps if s.get("tool") == "solve_schedule"), {})
    # The fact check is its own "check_facts" step ({"ok": ...}); older traces put it on
    # the "explain" step as fact_check_passed.
    passed = None
    for tool, key in (("check_facts", "ok"), ("explain", "fact_check_passed")):
        step = next((s for s in steps if s.get("tool") == tool), None)
        out = (step or {}).get("output") or {}
        if key in out:
            passed = out[key]
            break
    return {
        "solve_s": (solve.get("output") or {}).get("solve_s"),
        "faithful": None if passed is None else bool(passed),
        "llm_calls": trace.get("llm_calls", 0) or 0,
        "tokens": trace.get("tokens", 0) or 0,
    }


# ---------- Run ----------

def run(label: str, url: str | None, cases_path: Path, data_dir: Path, reload_data: bool) -> dict:
    if reload_data:
        loader.load_folder(data_dir)
    problem = loader.load_problem()
    base_due = {o.order_id: o.due for o in problem.orders}
    client = Client(url)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]

    rows = []
    for case in cases:
        events = case_disruptions(case, data_dir)
        due = {**base_due, **{e.target: e.due for e in events if e.kind == "rush_order"}}
        t0 = time.perf_counter()
        try:
            status, resp = client.analyze(request_body(case, events))
        except Exception as exc:  # noqa: BLE001 - record and keep going
            status, resp = 0, {"error": str(exc)}
        latency = time.perf_counter() - t0

        jobs = _jobs(resp) if status == 200 else []
        validator = resp.get("validator") or {}
        api_ok = validator.get("all_ok") if validator else None
        own_ok = independent_check(problem, jobs, events) if jobs else None
        plan_ok = None if not jobs else all(v is not False for v in (api_ok, own_ok))
        trace = client.trace(resp["run_id"]) if resp.get("run_id") else {}
        fails = ([f"HTTP {status}"] if status != 200 else []) + \
            check_case(case["expected"], resp, jobs, due, plan_ok)
        kpis = resp.get("kpis") or {}
        done = order_completion(jobs)
        rows.append({
            "id": case["id"], "category": case["category"], "run_id": resp.get("run_id"), "status": status,
            "answer_type": resp.get("answer_type"), "passed": not fails, "fails": fails,
            "jobs": len(jobs), "plan_ok": plan_ok, "api_validator_ok": api_ok, "own_checker_ok": own_ok,
            "late_orders": kpis.get("late_orders"), "total_lateness_h": kpis.get("total_lateness_h"),
            "overtime_h": kpis.get("overtime_h"), "changeovers": kpis.get("changeovers"),
            "moved_jobs": kpis.get("moved_jobs"),
            "late_by_plan": sorted(o for o, end in done.items() if o in due and end > due[o]),
            "latency_s": round(latency, 3), **_trace_facts(trace),
        })
        mark = "PASS" if not fails else "FAIL"
        print(f"{case['id']:<4} {case['category']:<17} {mark}  {resp.get('answer_type')!s:<21} "
              f"{latency:6.2f}s  {'; '.join(fails)}")

    result = {"label": label, "run_at": datetime.now().isoformat(timespec="seconds"),
              "config": {"llm_provider": config.LLM_PROVIDER, "llm_model": config.LLM_MODEL,
                         "mock_llm": config.MOCK_LLM, "solver_time_limit_s": config.SOLVER_TIME_LIMIT_S},
              "summary": summarize(rows), "cases": rows}
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{label}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {out}")
    return result


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, round(q * (len(values) - 1)))], 3)


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else None


def summarize(rows: list[dict]) -> dict:
    planned = [r for r in rows if r["jobs"]]
    replans = [r for r in planned if r["category"] in {"disruption", "rush"}]
    faith = [r["faithful"] for r in rows if r["faithful"] is not None]
    latencies = [r["latency_s"] for r in rows if r["status"] == 200]
    solves = [r["solve_s"] for r in rows if r["solve_s"] is not None]
    return {
        "cases": len(rows),
        "cases_passed": sum(r["passed"] for r in rows),
        "answer_type_accuracy": round(sum(r["status"] == 200 and not any(f.startswith("answer_type")
                                                                          for f in r["fails"])
                                          for r in rows) / len(rows), 3),
        "plans": len(planned),
        "plan_validity": round(sum(bool(r["plan_ok"]) for r in planned) / len(planned), 3) if planned else None,
        "avg_late_orders": _mean(r["late_orders"] for r in planned),
        "avg_total_lateness_h": _mean(r["total_lateness_h"] for r in planned),
        "avg_overtime_h": _mean(r["overtime_h"] for r in planned),
        "avg_changeovers": _mean(r["changeovers"] for r in planned),
        "avg_moved_jobs_replan": _mean(r["moved_jobs"] for r in replans),
        "solve_s_p50": _pct(solves, 0.5), "solve_s_max": max(solves) if solves else None,
        "latency_s_p50": _pct(latencies, 0.5), "latency_s_p95": _pct(latencies, 0.95),
        "faithfulness": round(sum(faith) / len(faith), 3) if faith else None,
        "llm_calls": sum(r["llm_calls"] for r in rows), "tokens": sum(r["tokens"] for r in rows),
    }


def compare(paths: list[Path]) -> str:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    keys = list(runs[0]["summary"])
    lines = ["| metric | " + " | ".join(r["label"] for r in runs) + " |",
             "|---|" + "---|" * len(runs)]
    lines += [f"| {k} | " + " | ".join(str(r["summary"].get(k)) for r in runs) + " |" for k in keys]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation set against /analyze.")
    parser.add_argument("--label", default="baseline", help="name for this configuration's results")
    parser.add_argument("--url", help="running API, e.g. http://localhost:8000 (default: in-process)")
    parser.add_argument("--cases", type=Path, default=EVAL_DIR / "cases.json")
    parser.add_argument("--data", type=Path, default=config.DATA_DIR, help="folder with the CSV pack")
    parser.add_argument("--no-reload", action="store_true", help="don't reload the CSV pack first")
    parser.add_argument("--compare", nargs="+", type=Path, help="print a comparison table of saved results")
    args = parser.parse_args(argv)

    if args.compare:
        print(compare(args.compare))
        return 0
    result = run(args.label, args.url, args.cases, args.data, not args.no_reload)
    print("\n" + json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
