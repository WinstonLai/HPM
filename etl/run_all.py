"""Run the full ETL pipeline end to end:
  1. scrape + geocode the mall registry
  2. download raw amenity/context datasets
  3. join + normalise into per-mall category scores
  4. compute the default composite Health Readiness Index

Re-run any time to refresh the dashboard's data (a repeatable nationwide
assessment). Safe to re-run repeatedly: raw downloads
and the mall registry are cached and skipped unless --force is passed.

A --limit debug run writes to data/processed_limited/ (or --out-dir), never to
the committed data/processed/ CSVs.
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
import provenance  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download/re-scrape even if cached")
    parser.add_argument("--limit", type=int, default=None, help="cap mall count (debug)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="write processed CSVs here instead of data/processed/ "
                             "(default with --limit: data/processed_limited/)")
    parser.add_argument("--allow-missing", action="store_true",
                        help="carry on when a dataset fails to download or a score column ends up constant")
    args = parser.parse_args()

    processed_dir = PROCESSED_DIR
    out_dir = args.out_dir or (provenance.SCRATCH_DIR if args.limit else None)
    if out_dir:
        processed_dir = provenance.redirect_processed_dir(
            out_dir.resolve(), build_category_scores, build_index, build_mall_registry)
        print(f"Writing processed CSVs to {processed_dir} (not data/processed/)")

    processed_dir.mkdir(parents=True, exist_ok=True)
    malls_path = processed_dir / "malls.csv"
    if args.force or not malls_path.exists():
        print("=== Step 1/4: mall registry ===")
        df = build_mall_registry.build_registry(limit=args.limit)
        df.to_csv(malls_path, index=False)
        print(f"Wrote {len(df)} malls to {malls_path}")
    else:
        print(f"=== Step 1/4: mall registry (cached: {malls_path}) ===")
        if args.limit:
            print(f"  [warn] --limit {args.limit} is ignored because {malls_path} already exists; "
                  "combine it with --force to rebuild a limited registry")

    print("\n=== Step 2/4: download amenity/context datasets ===")
    failed = build_amenities.download_all(force=args.force)
    if failed and not args.allow_missing:
        sys.exit(f"\n{len(failed)} download(s) failed: {', '.join(failed)}. Fix and re-run, "
                 "or pass --allow-missing to score those categories from nothing.")

    print("\n=== Step 3/4: category scores ===")
    build_category_scores.build_category_scores(allow_missing=args.allow_missing)

    print("\n=== Step 4/4: composite index ===")
    build_index.build_index()

    print("\nETL pipeline complete.")


if __name__ == "__main__":
    main()
