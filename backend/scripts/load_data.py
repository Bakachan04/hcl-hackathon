"""CLI loader for Annex B CSVs. Owner: Lavanya.

    python scripts/load_data.py <folder>                 # loads the four Annex B files
    python scripts/load_data.py <folder> --disruption disruption_2.csv

Each file is checked row by row: good rows replace the stored table, bad rows are
reported with the reason. Exit code 1 if a required table failed to load.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app import config, loader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Annex B CSV files into the store.")
    parser.add_argument("folder", type=Path, nargs="?", default=config.DATA_DIR)
    parser.add_argument("--disruption", help="disruption file name in the folder (default disruption.csv)")
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"Folder not found: {args.folder}")
        return 1

    print(f"Loading {args.folder.resolve()} into {config.DB_PATH}")
    results = loader.load_folder(args.folder)
    if args.disruption:
        results["disruption"] = loader.load_table("disruption", args.folder / args.disruption)

    print(f"\n{'table':<20} {'status':<8} {'loaded':>7} {'rejected':>9}")
    for table, r in results.items():
        print(f"{table:<20} {r.status:<8} {r.rows_loaded:>7} {r.rows_rejected:>9}")
    for table, r in results.items():
        for err in r.errors:
            print(f"  [{table}] {err}")

    failed = [t for t, r in results.items() if r.status == "failed" and t != "disruption"]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    print("\nNext: python scripts/validate_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
