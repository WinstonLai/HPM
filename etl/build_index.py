"""Apply the charter's illustrative weights to category_scores.csv and write
the default static ranking (rank, tier, Top 10/20/50, strategic quadrant) to
data/processed/hpm_index.csv. This is the view shown before a user touches
any What-If Simulator slider in the dashboard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring_formula import add_strategic_quadrant, compute_index  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def build_index() -> pd.DataFrame:
    category_scores = pd.read_csv(PROCESSED_DIR / "category_scores.csv")
    df = compute_index(category_scores)
    df = add_strategic_quadrant(df)
    out_path = PROCESSED_DIR / "hpm_index.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} ranked malls to {out_path}")
    print(df[["rank", "name", "hpm_index", "tier", "quadrant"]].head(10).to_string(index=False))
    return df


if __name__ == "__main__":
    build_index()
