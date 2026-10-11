"""Runs data validation checks and prints the report. Owner: Lavanya.

    python scripts/validate_data.py                       # checks the stored data
    python scripts/validate_data.py --load ../data/raw    # load a folder first, then check
    python scripts/validate_data.py --no-card             # skip the data-card row-count check
    python scripts/validate_data.py --save ../docs/validation_output.txt

Exit code 0 if every check passes, 1 otherwise.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app import config, loader, store, validation

DATA_CARD = Path(__file__).resolve().parents[2] / "docs" / "data_card.md"


def report(results: list[dict]) -> str:
    width = max(len(r["check"]) for r in results)
    lines = [f"{'CHECK':<{width}}  RESULT  DETAIL", "-" * (width + 40)]
    for r in results:
        lines.append(f"{r['check']:<{width}}  {'PASS' if r['passed'] else 'FAIL':<6}  {r['detail']}")
    passed = sum(r["passed"] for r in results)
    lines += ["-" * (width + 40),
              (f"{'OVERALL':<{width}}  {'PASS' if passed == len(results) else 'FAIL':<6}  "
               f"{passed}/{len(results)} checks passed")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the loaded data (guide 4.5).")
    parser.add_argument("--load", type=Path, help="load this folder of CSVs first")
    parser.add_argument("--card", type=Path, default=DATA_CARD, help="data card with expected row counts")
    parser.add_argument("--no-card", action="store_true", help="skip the row-count check")
    parser.add_argument("--save", type=Path, help="also write the report to this file")
    args = parser.parse_args(argv)

    out = []
    if args.load:
        for table, r in loader.load_folder(args.load).items():
            out.append(f"loaded {table}: {r.status}, {r.rows_loaded} loaded, {r.rows_rejected} rejected")

    try:
        problem = loader.load_problem()
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    expected = None
    if not args.no_card and args.card.exists():
        expected = validation.counts_from_data_card(args.card)

    results = validation.run_checks(problem, expected)
    counts = store.table_counts()
    header = [
        f"Data validation report  {datetime.now():%Y-%m-%d %H:%M}",
        f"Store: {config.DB_PATH.name}   plan start: {problem.plan_start:%Y-%m-%d %H:%M}",
        "Stored rows: " + ", ".join(f"{t}={n}" for t, n in counts.items()),
        f"Data card: {args.card.name if expected is not None else 'not used'}",
        "",
    ]
    text = "\n".join(out + ([""] if out else []) + header) + report(results)
    print(text)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(text + "\n", encoding="utf-8")
    return 0 if validation.all_passed(results) else 1


if __name__ == "__main__":
    sys.exit(main())
