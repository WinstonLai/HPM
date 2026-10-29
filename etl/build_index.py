"""Apply the reference weights to category_scores.csv and write
the default static ranking (rank, tier, Top 10/20/50, strategic quadrant) to
data/processed/hpm_index.csv. This is the view shown before a user touches
any What-If Simulator slider in the dashboard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring_formula import (  # noqa: E402
    DEFAULT_DEMAND_WEIGHTS, DEFAULT_SUPPLY_WEIGHTS, DEMAND_BLOCK_WEIGHT, SUPPLY_BLOCK_WEIGHT, TIER_THRESHOLDS,
    add_strategic_quadrant, compute_index,
)
import provenance  # noqa: E402
import validate  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def build_index() -> pd.DataFrame:
    category_scores = pd.read_csv(PROCESSED_DIR / "category_scores.csv")
    df = compute_index(category_scores)
    df = add_strategic_quadrant(df)
    validate.enforce("index", *validate.validate_index(df))
    out_path = PROCESSED_DIR / "hpm_index.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} ranked malls to {out_path}")
    provenance.update_meta("index", {
        "n_malls": int(len(df)),
        "supply_weights": {k: round(v, 2) for k, v in DEFAULT_SUPPLY_WEIGHTS.items()},
        "demand_weights": {k: round(v, 2) for k, v in DEFAULT_DEMAND_WEIGHTS.items()},
        "supply_block_weight": SUPPLY_BLOCK_WEIGHT, "demand_block_weight": DEMAND_BLOCK_WEIGHT,
        "tier_thresholds": TIER_THRESHOLDS,
        "top10": df.nsmallest(10, "rank")["name"].tolist(),
    })
    print(df[["rank", "name", "hpm_index", "tier", "quadrant"]].head(10).to_string(index=False))
    return df


if __name__ == "__main__":
    build_index()
