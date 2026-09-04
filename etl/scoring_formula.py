"""Single source of truth for the HPM composite index formula, per the
charter's "Composite Health Promoting Mall Index" section:

    HPM Index = Supply Readiness (70%) + Demand Opportunity (30%)
    Supply Readiness  = Dining + Fitness + H365 Presence + Healthcare
                         + Infrastructure + Partnership Readiness
    Demand Opportunity = Reach & Population + Accessibility + Engagement Gap

The charter's per-category "illustrative weights" (A 25%, B 20%, C 15%,
D 10%, E 10%, F 10% -- these six sum to 90, not 100, in the source document)
are renormalised to sum to 100 *within* Supply Readiness, since Supply itself
is only 70% of the final index and Category G ("Demand Potential") is
represented by the separate Reach/Accessibility/Engagement-Gap block rather
than as a seventh flat weight.

This module is imported both by the one-off ETL build step (etl/build_index.py,
which produces the default static ranking) and by the Streamlit "What-If
Simulator" page (app/lib/scoring.py), so a slider change and the offline
build always agree on how a score is computed.
"""
from __future__ import annotations

import pandas as pd

# --- Supply Readiness sub-weights (charter's illustrative weights, renormalised to 100) ---
_RAW_SUPPLY_WEIGHTS = {
    "A_dining_score": 25,
    "B_fitness_score": 20,
    "C_engagement_score": 15,   # "H365 Presence" in the composite formula
    "D_healthcare_score": 10,
    "E_infra_score": 10,
    "F_partnership_score": 10,
}
_SUPPLY_WEIGHT_SUM = sum(_RAW_SUPPLY_WEIGHTS.values())
DEFAULT_SUPPLY_WEIGHTS = {k: v / _SUPPLY_WEIGHT_SUM * 100 for k, v in _RAW_SUPPLY_WEIGHTS.items()}

# --- Demand Opportunity sub-weights: Reach&Population / Accessibility / Engagement Gap ---
DEFAULT_DEMAND_WEIGHTS = {
    "reach_population_score": 100 / 3,
    "accessibility_score": 100 / 3,
    "engagement_gap_score": 100 / 3,
}

SUPPLY_BLOCK_WEIGHT = 70
DEMAND_BLOCK_WEIGHT = 30

CATEGORY_LABELS = {
    "A_dining_score": "Healthy Dining",
    "B_fitness_score": "Physical Activity",
    "C_engagement_score": "H365 & HPB Engagement",
    "D_healthcare_score": "Healthcare",
    "E_infra_score": "Healthy Infrastructure",
    "F_partnership_score": "Partnership Readiness",
    "reach_population_score": "Reach & Population",
    "accessibility_score": "Accessibility",
    "engagement_gap_score": "Engagement Gap",
}

TIERS = ["Bronze", "Silver", "Gold", "Platinum"]


def _weighted_sum(df: pd.DataFrame, weights: dict) -> pd.Series:
    total_weight = sum(weights.values()) or 1.0
    score = pd.Series(0.0, index=df.index)
    for col, w in weights.items():
        if col in df.columns:
            score = score + df[col].fillna(0) * w
    return score / total_weight


def compute_index(
    category_scores: pd.DataFrame,
    supply_weights: dict | None = None,
    demand_weights: dict | None = None,
    supply_block_weight: float = SUPPLY_BLOCK_WEIGHT,
    demand_block_weight: float = DEMAND_BLOCK_WEIGHT,
) -> pd.DataFrame:
    """Return a copy of `category_scores` with supply_score, demand_score,
    hpm_index, rank, and tier columns computed from the given weights
    (falling back to the charter's illustrative defaults)."""
    supply_weights = supply_weights or DEFAULT_SUPPLY_WEIGHTS
    demand_weights = demand_weights or DEFAULT_DEMAND_WEIGHTS

    df = category_scores.copy()
    df["supply_score"] = _weighted_sum(df, supply_weights)
    df["demand_score"] = _weighted_sum(df, demand_weights)

    block_total = supply_block_weight + demand_block_weight or 1.0
    df["hpm_index"] = (
        df["supply_score"] * supply_block_weight + df["demand_score"] * demand_block_weight
    ) / block_total

    df = df.sort_values("hpm_index", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    df["tier"] = pd.qcut(df["hpm_index"], q=4, labels=TIERS, duplicates="drop")
    n = len(df)
    df["top10"] = df["rank"] <= min(10, n)
    df["top20"] = df["rank"] <= min(20, n)
    df["top50"] = df["rank"] <= min(50, n)
    return df


def strategic_quadrant(row) -> str:
    """2x2 matrix from the charter's 'Potential Enhancement' section:
    High Readiness + High Demand -> Pioneer HPM
    High Readiness + Low Demand  -> Quick Wins
    Low Readiness  + High Demand -> Strategic Investment
    Low Readiness  + Low Demand  -> Future Monitoring
    """
    high_supply = row["supply_high"]
    high_demand = row["demand_high"]
    if high_supply and high_demand:
        return "Pioneer HPM"
    if high_supply and not high_demand:
        return "Quick Wins"
    if not high_supply and high_demand:
        return "Strategic Investment"
    return "Future Monitoring"


def add_strategic_quadrant(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    supply_med = df["supply_score"].median()
    demand_med = df["demand_score"].median()
    df["supply_high"] = df["supply_score"] >= supply_med
    df["demand_high"] = df["demand_score"] >= demand_med
    df["quadrant"] = df.apply(strategic_quadrant, axis=1)
    return df
