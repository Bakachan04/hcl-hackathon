"""Synthetic data generator. Owner: Lavanya.

Writes the four Annex B files (plus two extra disruption files for the evaluation):

    python scripts/generate_data.py --seed 42 --out ../data/raw

The plant layout (machines, routings, changeovers, roster) is fixed by design so the
planted edge cases are always in the same place. The seed drives the orders: product mix,
quantities, due dates, priorities and customers. Same seed -> byte-identical files.
See docs/data_card.md for what each trap is and where it is planted.
"""

import argparse
import csv
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

TIME_FMT = "%Y-%m-%d %H:%M"
PLAN_START = datetime(2026, 10, 12, 6, 0)
N_ORDERS = 45

# ---------- Fixed plant layout ----------

MACHINES = ["CNC-1", "CNC-2", "CNC-3", "CNC-4", "LTH-1", "LTH-2", "ASM-1", "ASM-2"]

# product, step, machine_group, minutes_per_unit, skill_required
ROUTINGS = [
    ("PA", 1, "CNC-1|CNC-2", 1.5, "L1"),
    ("PA", 2, "LTH-1|LTH-2", 1.0, "L2"),
    ("PA", 3, "ASM-1|ASM-2", 0.8, "L1"),
    ("PB", 1, "CNC-2|CNC-3|CNC-4", 2.0, "L1"),
    ("PB", 2, "ASM-1|ASM-2", 1.0, "L2"),
    ("PC", 1, "CNC-3", 2.5, "L2"),        # TRAP: PC step 1 runs only on CNC-3, which breaks
    ("PC", 2, "LTH-1|LTH-2", 1.2, "L1"),
    ("PD", 1, "CNC-1|CNC-4", 1.8, "L2"),
    ("PD", 2, "LTH-2", 1.4, "L3"),        # TRAP: needs L3, one L3 operator per shift
    ("PD", 3, "ASM-2", 1.0, "L1"),
]
PRODUCTS = ["PA", "PB", "PC", "PD"]
PRODUCT_WEIGHTS = [0.30, 0.30, 0.20, 0.20]
MAX_MPU = {p: max(r[3] for r in ROUTINGS if r[0] == p) for p in PRODUCTS}

# TRAP: direction matters (A->B != B->A) for every pair.
CHANGEOVERS = {
    ("PA", "PB"): 20, ("PB", "PA"): 45,
    ("PA", "PC"): 30, ("PC", "PA"): 15,
    ("PA", "PD"): 40, ("PD", "PA"): 25,
    ("PB", "PC"): 35, ("PC", "PB"): 50,
    ("PB", "PD"): 25, ("PD", "PB"): 30,
    ("PC", "PD"): 60, ("PD", "PC"): 20,
}

# operator_id, skill, shift. TRAP: OP-01 / OP-09 are the only L3 on shifts A / B.
OPERATORS = [
    ("OP-01", "L3", "A"), ("OP-02", "L2", "A"), ("OP-03", "L2", "A"), ("OP-04", "L1", "A"),
    ("OP-05", "L1", "A"), ("OP-06", "L2", "A"), ("OP-07", "L1", "A"), ("OP-08", "L1", "A"),
    ("OP-09", "L3", "B"), ("OP-10", "L2", "B"), ("OP-11", "L2", "B"), ("OP-12", "L1", "B"),
    ("OP-13", "L1", "B"), ("OP-14", "L2", "B"), ("OP-15", "L1", "B"),
]

CUSTOMERS = [f"Synthetic Customer {i:02d}" for i in range(1, 9)]
KEY_CUSTOMERS = {"Synthetic Customer 01", "Synthetic Customer 02"}  # customer_tier = 1

# Orders whose fields are pinned so the traps are always where the data card says.
SHARED_DUE = datetime(2026, 10, 12, 18, 0)
PINNED = {
    # Work in progress already running at plan start.
    "O-101": {"product": "PA", "qty": 60, "priority": 2, "wip": ("CNC-1", "OP-02", False)},
    "O-102": {"product": "PC", "qty": 40, "priority": 1, "wip": ("CNC-3", "OP-03", False)},
    "O-103": {"product": "PB", "qty": 50, "priority": 3, "wip": ("CNC-4", "OP-04", True)},
    # Only CNC-3 can run its first step; due before CNC-3 comes back.
    "O-107": {"product": "PC", "qty": 48, "priority": 1, "due": datetime(2026, 10, 12, 16, 0)},
    # Priority-1 order sharing its due date with rush order R-201.
    "O-110": {"product": "PB", "qty": 40, "priority": 1, "due": SHARED_DUE},
}

# event_id, kind, at, target, duration_h, product, qty, due, priority, customer
DISRUPTIONS = {
    "disruption.csv": [
        ("D-1", "breakdown", "2026-10-12 10:00", "CNC-3", 6, "", "", "", "", ""),
        # TRAP: PC needs CNC-3 (down until 16:00); 150 + 72 min of work -> earliest end 19:42,
        # so R-201 cannot be on time in any plan. Same due date as priority-1 order O-110.
        ("D-2", "rush_order", "2026-10-12 12:00", "R-201", "", "PC", 60,
         SHARED_DUE.strftime(TIME_FMT), 1, "Synthetic Customer 01"),
    ],
    "disruption_2.csv": [
        ("D-3", "breakdown", "2026-10-12 08:00", "CNC-1", 4, "", "", "", "", ""),
        ("D-4", "rush_order", "2026-10-12 09:00", "R-202", "", "PA", 50,
         "2026-10-13 12:00", 1, "Synthetic Customer 02"),
    ],
    "disruption_3.csv": [
        # LTH-2 is the only machine for PD step 2.
        ("D-5", "breakdown", "2026-10-12 14:00", "LTH-2", 5, "", "", "", "", ""),
        ("D-6", "rush_order", "2026-10-12 15:00", "R-203", "", "PB", 45,
         "2026-10-13 10:00", 1, "Synthetic Customer 03"),
    ],
}

ORDER_COLS = ["order_id", "product", "qty", "due", "priority", "customer", "customer_tier",
              "wip_step", "wip_machine", "wip_operator", "wip_start", "wip_end", "movable"]
ROUTING_COLS = ["product", "step", "machine_group", "minutes_per_unit", "skill_required"]
CS_COLS = ["from_product", "to_product", "minutes", "operator_id", "skill", "shift"]
DISRUPTION_COLS = ["event_id", "kind", "at", "target", "duration_h",
                   "product", "qty", "due", "priority", "customer"]


def _random_due(rng: random.Random) -> datetime:
    """A due time inside working hours, from day 1 afternoon to day 3 evening."""
    day = rng.choices([0, 1, 2], weights=[0.2, 0.4, 0.4])[0]
    hour = rng.randint(12, 21) if day == 0 else rng.randint(8, 21)
    return PLAN_START.replace(hour=hour) + timedelta(days=day)


def make_orders(rng: random.Random) -> list[dict]:
    rows = []
    for i in range(N_ORDERS):
        order_id = f"O-{101 + i}"
        pin = PINNED.get(order_id, {})
        product = pin.get("product") or rng.choices(PRODUCTS, weights=PRODUCT_WEIGHTS)[0]
        # Keep every job <= 4 h: qty * minutes_per_unit <= 240 on the slowest step.
        qty = pin.get("qty") or rng.randint(20, min(80, int(240 // MAX_MPU[product])))
        due = pin.get("due") or _random_due(rng)
        priority = pin.get("priority") or rng.choices([1, 2, 3], weights=[0.2, 0.4, 0.4])[0]
        customer = rng.choice(CUSTOMERS)
        row = {
            "order_id": order_id, "product": product, "qty": qty,
            "due": due.strftime(TIME_FMT), "priority": priority, "customer": customer,
            "customer_tier": 1 if customer in KEY_CUSTOMERS else 2,
            "wip_step": "", "wip_machine": "", "wip_operator": "", "wip_start": "",
            "wip_end": "", "movable": "true",
        }
        if "wip" in pin:
            machine, operator, movable = pin["wip"]
            mpu = next(r[3] for r in ROUTINGS if r[0] == product and r[1] == 1)
            end = PLAN_START + timedelta(minutes=math.ceil(qty * mpu))
            row.update(wip_step=1, wip_machine=machine, wip_operator=operator,
                       wip_start=PLAN_START.strftime(TIME_FMT), wip_end=end.strftime(TIME_FMT),
                       movable="true" if movable else "false")
        rows.append(row)
    return rows


def _write(path: Path, cols: list[str], rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(cols)
        for row in rows:
            writer.writerow([row[c] for c in cols] if isinstance(row, dict) else row)


def generate(seed: int, out: Path) -> dict[str, int]:
    """Write all files into `out` and return row counts per file."""
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)

    orders = make_orders(rng)
    cs_rows = [(a, b, m, "", "", "") for (a, b), m in CHANGEOVERS.items()]
    cs_rows += [("", "", "", op, skill, shift) for op, skill, shift in OPERATORS]

    _write(out / "orders.csv", ORDER_COLS, orders)
    _write(out / "routings_machines.csv", ROUTING_COLS, ROUTINGS)
    _write(out / "changeovers_skills.csv", CS_COLS, cs_rows)
    for name, rows in DISRUPTIONS.items():
        _write(out / name, DISRUPTION_COLS, rows)

    counts = {"orders.csv": len(orders), "routings_machines.csv": len(ROUTINGS),
              "changeovers_skills.csv": len(cs_rows)}
    counts.update({name: len(rows) for name, rows in DISRUPTIONS.items()})
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic data pack.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "data" / "raw")
    args = parser.parse_args(argv)

    counts = generate(args.seed, args.out)
    print(f"Wrote data pack (seed {args.seed}) to {args.out.resolve()}")
    for name, n in counts.items():
        print(f"  {name:<24} {n:>3} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
