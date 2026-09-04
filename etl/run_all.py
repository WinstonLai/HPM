"""Run the full ETL pipeline end to end:
  1. scrape + geocode the mall registry
  2. download raw amenity/context datasets
  3. join + normalise into per-mall category scores
  4. compute the default composite HPM index

Re-run any time to refresh the dashboard's data (the "repeatable nationwide
assessment" the charter calls for). Safe to re-run repeatedly: raw downloads
and the mall registry are cached and skipped unless --force is passed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_amenities  # noqa: E402
import build_category_scores  # noqa: E402
import build_index  # noqa: E402
import build_mall_registry  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download/re-scrape even if cached")
    parser.add_argument("--limit", type=int, default=None, help="cap mall count (debug)")
    args = parser.parse_args()

    malls_path = PROCESSED_DIR / "malls.csv"
    if args.force or not malls_path.exists():
        print("=== Step 1/4: mall registry ===")
        df = build_mall_registry.build_registry(limit=args.limit)
        df.to_csv(malls_path, index=False)
        print(f"Wrote {len(df)} malls to {malls_path}")
    else:
        print(f"=== Step 1/4: mall registry (cached: {malls_path}) ===")

    print("\n=== Step 2/4: download amenity/context datasets ===")
    build_amenities.download_all(force=args.force)

    print("\n=== Step 3/4: category scores ===")
    build_category_scores.build_category_scores()

    print("\n=== Step 4/4: composite index ===")
    build_index.build_index()

    print("\nETL pipeline complete.")


if __name__ == "__main__":
    main()
