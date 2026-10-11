"""CSV -> checked tables -> Problem. Owner: Lavanya.

load_table() checks one Annex B file row by row, keeps the good rows (stored as cleaned
text in the SQLite store) and reports the bad ones with reasons. load_problem() builds
the solver's Problem model from whatever is currently stored.

Only the Annex B columns are required. Our extra columns (WIP, customer_tier, rush-order
details) are read when present and ignored when missing.
"""

import io
import re
from collections.abc import Callable
from datetime import datetime, time
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from app import config, store
from app.schemas import (
    TIME_FMT,
    Changeover,
    Disruption,
    LoadResult,
    Operator,
    Order,
    Problem,
    RoutingStep,
)

REQUIRED = {
    "orders": ["order_id", "product", "qty", "due", "priority", "customer"],
    "routings_machines": ["product", "step", "machine_group", "minutes_per_unit", "skill_required"],
    "changeovers_skills": ["from_product", "to_product", "minutes", "operator_id", "skill", "shift"],
    "disruption": ["event_id", "kind", "at", "target", "duration_h"],
}
OPTIONAL = {
    "orders": ["customer_tier", "wip_step", "wip_machine", "wip_operator", "wip_start",
               "wip_end", "movable"],
    "routings_machines": [],
    "changeovers_skills": [],
    "disruption": ["product", "qty", "due", "priority", "customer"],
}
TABLES = tuple(REQUIRED)
MAX_ERRORS = 50  # keep responses readable when a whole file is bad

_TRUE = {"true", "1", "yes", "y", "t"}
_FALSE = {"false", "0", "no", "n", "f"}


# ---------- Value parsing ----------

def _opt(value: str) -> str | None:
    return value if value != "" else None


def parse_dt(value: str) -> datetime:
    """'2026-10-12 06:00' plus ISO variants ('2026-10-12T06:00:00', '2026-10-12')."""
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"bad datetime {value!r}, expected YYYY-MM-DD HH:MM") from None


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime(TIME_FMT) if value else ""


def parse_bool(value: str, default: bool = True) -> bool:
    v = value.strip().lower()
    if v == "":
        return default
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(f"bad boolean {value!r}")


def parse_skill(value: str) -> str:
    """'L2', 'l2' or '2' -> 'L2'."""
    m = re.fullmatch(r"[Ll]?\s*(\d+)", value.strip())
    if not m:
        raise ValueError(f"bad skill level {value!r}, expected L1, L2, L3")
    return f"L{int(m.group(1))}"


def parse_machines(value: str) -> list[str]:
    """'CNC-3|CNC-5' -> ['CNC-3', 'CNC-5']."""
    return [m.strip() for m in value.split("|") if m.strip()]


def parse_shift(value: str) -> tuple[time, time]:
    """Shift code ('A', 'B') from config.SHIFTS, or an explicit range '06:00-14:00'."""
    code = value.strip().upper()
    if code in config.SHIFTS:
        return config.SHIFTS[code]
    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", value.strip())
    if m:
        h1, m1, h2, m2 = map(int, m.groups())
        return time(h1, m1), time(h2, m2)
    raise ValueError(f"unknown shift {value!r}; expected {'/'.join(config.SHIFTS)} or HH:MM-HH:MM")


def _int(value: str) -> int:
    f = float(value)
    if not f.is_integer():
        raise ValueError(f"expected a whole number, got {value!r}")
    return int(f)


# ---------- Row parsers: dict of text -> (model, cleaned row) ----------

def _order(r: dict) -> tuple[Order, dict]:
    o = Order(
        order_id=r["order_id"], product=r["product"], qty=_int(r["qty"]), due=parse_dt(r["due"]),
        priority=_int(r["priority"]), customer=r["customer"],
        customer_tier=_int(r["customer_tier"]) if r.get("customer_tier") else None,
        wip_step=_int(r["wip_step"]) if r.get("wip_step") else None,
        wip_machine=_opt(r.get("wip_machine", "")), wip_operator=_opt(r.get("wip_operator", "")),
        wip_start=parse_dt(r["wip_start"]) if r.get("wip_start") else None,
        wip_end=parse_dt(r["wip_end"]) if r.get("wip_end") else None,
        movable=parse_bool(r.get("movable", "")),
    )
    if o.wip_step is not None and not (o.wip_machine and o.wip_start and o.wip_end):
        raise ValueError("wip_step set but wip_machine/wip_start/wip_end missing")
    if o.wip_start and o.wip_end and o.wip_end <= o.wip_start:
        raise ValueError("wip_end must be after wip_start")
    return o, _order_row(o)


def _order_row(o: Order) -> dict:
    return {
        "order_id": o.order_id, "product": o.product, "qty": str(o.qty), "due": _fmt_dt(o.due),
        "priority": str(o.priority), "customer": o.customer,
        "customer_tier": "" if o.customer_tier is None else str(o.customer_tier),
        "wip_step": "" if o.wip_step is None else str(o.wip_step),
        "wip_machine": o.wip_machine or "", "wip_operator": o.wip_operator or "",
        "wip_start": _fmt_dt(o.wip_start), "wip_end": _fmt_dt(o.wip_end),
        "movable": "true" if o.movable else "false",
    }


def _routing(r: dict) -> tuple[RoutingStep, dict]:
    s = RoutingStep(product=r["product"], step=_int(r["step"]),
                    machines=parse_machines(r["machine_group"]),
                    minutes_per_unit=float(r["minutes_per_unit"]),
                    skill_required=parse_skill(r["skill_required"]))
    return s, {"product": s.product, "step": str(s.step), "machine_group": "|".join(s.machines),
               "minutes_per_unit": repr(s.minutes_per_unit), "skill_required": s.skill_required}


def _changeover_or_operator(r: dict) -> tuple[Changeover | Operator, dict]:
    """A row is a changeover (from/to/minutes) or an operator (id/skill/shift), not both."""
    is_co = any(r.get(c) for c in ("from_product", "to_product", "minutes"))
    is_op = any(r.get(c) for c in ("operator_id", "skill", "shift"))
    blank = {c: "" for c in REQUIRED["changeovers_skills"]}
    if is_co and is_op:
        raise ValueError("row mixes changeover and operator fields; use separate rows")
    if is_co:
        c = Changeover(from_product=r["from_product"], to_product=r["to_product"],
                       minutes=_int(r["minutes"]))
        if not c.from_product or not c.to_product:
            raise ValueError("changeover needs from_product and to_product")
        return c, {**blank, "from_product": c.from_product, "to_product": c.to_product,
                   "minutes": str(c.minutes)}
    if is_op:
        start, end = parse_shift(r["shift"])
        op = Operator(operator_id=r["operator_id"], skill=parse_skill(r["skill"]),
                      shift=r["shift"].strip(), shift_start=start, shift_end=end)
        if not op.operator_id:
            raise ValueError("operator row needs operator_id")
        return op, {**blank, "operator_id": op.operator_id, "skill": op.skill, "shift": op.shift}
    raise ValueError("empty row")


def _disruption(r: dict) -> tuple[Disruption, dict]:
    d = Disruption(
        event_id=r["event_id"], kind=r["kind"].strip().lower(), at=parse_dt(r["at"]),
        target=r["target"], duration_h=float(r["duration_h"]) if r.get("duration_h") else None,
        product=_opt(r.get("product", "")), qty=_int(r["qty"]) if r.get("qty") else None,
        due=parse_dt(r["due"]) if r.get("due") else None,
        priority=_int(r["priority"]) if r.get("priority") else None,
        customer=_opt(r.get("customer", "")),
    )
    if d.kind == "breakdown" and d.duration_h is None:
        raise ValueError("breakdown needs duration_h")
    if d.kind == "rush_order" and not (d.product and d.qty and d.due):
        raise ValueError("rush_order needs product, qty and due columns")
    return d, {
        "event_id": d.event_id, "kind": d.kind, "at": _fmt_dt(d.at), "target": d.target,
        "duration_h": "" if d.duration_h is None else repr(d.duration_h),
        "product": d.product or "", "qty": "" if d.qty is None else str(d.qty),
        "due": _fmt_dt(d.due), "priority": "" if d.priority is None else str(d.priority),
        "customer": d.customer or "",
    }


def _key(table: str, model) -> tuple:
    """Rows with the same key are duplicates: the first one wins."""
    if table == "orders":
        return (model.order_id,)
    if table == "routings_machines":
        return (model.product, model.step)
    if table == "disruption":
        return (model.event_id,)
    if isinstance(model, Changeover):
        return ("changeover", model.from_product, model.to_product)
    return ("operator", model.operator_id)


PARSERS: dict[str, Callable[[dict], tuple]] = {
    "orders": _order, "routings_machines": _routing,
    "changeovers_skills": _changeover_or_operator, "disruption": _disruption,
}


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'row'}: {e['msg']}" for e in exc.errors())
    return str(exc)


# ---------- Public API ----------

def check_table(table: str, source) -> tuple[pd.DataFrame, LoadResult]:
    """Parse and check one CSV (path, bytes or file-like) without storing it."""
    if table not in REQUIRED:
        raise ValueError(f"unknown table {table!r}; expected one of {', '.join(TABLES)}")
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        raw = pd.read_csv(source, dtype=str, keep_default_na=False, skipinitialspace=True,
                          encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - any parse failure means the file is unusable
        return pd.DataFrame(), LoadResult(rows_loaded=0, rows_rejected=0, status="failed",
                                          errors=[f"could not read CSV: {exc}"])
    raw.columns = [c.strip().lower() for c in raw.columns]

    missing = [c for c in REQUIRED[table] if c not in raw.columns]
    if missing:
        return pd.DataFrame(), LoadResult(
            rows_loaded=0, rows_rejected=len(raw), status="failed",
            errors=[f"missing required column(s): {', '.join(missing)}"])

    parse = PARSERS[table]
    good, errors, seen = [], [], set()
    for i, rec in enumerate(raw.to_dict("records")):
        line = i + 2  # header is line 1
        rec = {k: str(v).strip() for k, v in rec.items()}
        try:
            model, row = parse(rec)
        except (ValidationError, ValueError, KeyError) as exc:
            errors.append(f"line {line}: {_reason(exc)}")
            continue
        key = _key(table, model)
        if key in seen:
            errors.append(f"line {line}: duplicate {'/'.join(map(str, key))}")
            continue
        seen.add(key)
        good.append(row)

    columns = REQUIRED[table] + OPTIONAL[table]
    df = pd.DataFrame(good, columns=columns)
    status = "failed" if not good else ("partial" if errors else "ok")
    shown = errors[:MAX_ERRORS] + ([f"... {len(errors) - MAX_ERRORS} more"] if len(errors) > MAX_ERRORS else [])
    return df, LoadResult(rows_loaded=len(good), rows_rejected=len(errors), status=status, errors=shown)


def load_table(table: str, path) -> LoadResult:
    """Check one CSV and, if any row is good, replace the stored table with the good rows."""
    df, result = check_table(table, path)
    if result.rows_loaded:
        store.save_table(table, df)
    return result


def load_folder(folder: Path) -> dict[str, LoadResult]:
    """Load every Annex B file found in `folder` (disruption.csv is optional)."""
    results = {}
    for table in TABLES:
        path = Path(folder) / f"{table}.csv"
        if path.exists():
            results[table] = load_table(table, path)
        elif table != "disruption":
            results[table] = LoadResult(rows_loaded=0, rows_rejected=0, status="failed",
                                        errors=[f"{path.name} not found in {folder}"])
    return results


def _models(table: str) -> list:
    return [PARSERS[table](row)[0] for row in store.read_table(table).to_dict("records")]


def load_problem() -> Problem:
    """Build the Problem from the stored tables. Raises if a required table is empty."""
    for table in ("orders", "routings_machines", "changeovers_skills"):
        if store.read_table(table).empty:
            raise RuntimeError(f"table {table!r} is empty: load data first (scripts/load_data.py)")
    routings = sorted(_models("routings_machines"), key=lambda s: (s.product, s.step))
    cs = _models("changeovers_skills")
    return Problem(
        orders=_models("orders"),
        routings=routings,
        changeovers=[m for m in cs if isinstance(m, Changeover)],
        operators=[m for m in cs if isinstance(m, Operator)],
        machines=sorted({m for s in routings for m in s.machines}),
        plan_start=config.PLAN_START,
    )


def load_disruptions() -> list[Disruption]:
    """Disruption events currently stored (empty list if none loaded)."""
    return _models("disruption")
