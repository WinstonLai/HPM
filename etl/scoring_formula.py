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

Categories C (H365 & HPB Engagement) and F (Partnership Readiness) are
PROXIES -- no public dataset measures the real thing -- and are coarse (C only
takes the values 0/50/100; F is non-zero for only a handful of malls). They
therefore start below the charter's illustrative weights (C 15 -> 10,
F 10 -> 5), and can be switched off entirely on the What-If Simulator via
`exclude_proxies`. The charter values are kept in CHARTER_SUPPLY_WEIGHTS.

A factor that is NaN for a mall means "not applicable" (e.g. Engagement Gap
for a mall with no residents in its catchment); that factor is left out and
the mall's block score is re-weighted over its remaining factors, rather than
being scored as a zero.

This module is imported both by the one-off ETL build step (etl/build_index.py,
which produces the default static ranking) and by the Streamlit "What-If
Simulator" page (app/lib/scoring.py), so a slider change and the offline
build always agree on how a score is computed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --- Supply Readiness sub-weights (renormalised to 100) ---
# The charter's illustrative weights, for reference / the Methodology page.
CHARTER_SUPPLY_WEIGHTS = {
    "A_dining_score": 25,
    "B_fitness_score": 20,
    "C_engagement_score": 15,   # "H365 Presence" in the composite formula
    "D_healthcare_score": 10,
    "E_infra_score": 10,
    "F_partnership_score": 10,
}
# Categories scored with a proxy rather than the metric the charter names.
PROXY_CATEGORIES = ("C_engagement_score", "F_partnership_score")
_RAW_SUPPLY_WEIGHTS = {
    "A_dining_score": 25,
    "B_fitness_score": 20,
    "C_engagement_score": 10,   # proxy (community-club proximity): charter 15
    "D_healthcare_score": 10,
    "E_infra_score": 10,
    "F_partnership_score": 5,   # proxy (landlord portfolio size): charter 10
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


def exclude_proxies(weights: dict) -> dict:
    """`weights` with the proxy categories (C, F) zeroed. The remaining
    weights are re-normalised by compute_index, so the others scale up."""
    return {k: (0 if k in PROXY_CATEGORIES else v) for k, v in weights.items()}


def _weighted_sum(df: pd.DataFrame, weights: dict) -> pd.Series:
    """Weighted average of the given score columns. A NaN score means "not
    applicable" and drops that factor (and its weight) for that row only; a
    column missing from `df` entirely counts as a score of 0."""
    num = pd.Series(0.0, index=df.index)
    den = pd.Series(0.0, index=df.index)
    for col, w in weights.items():
        if col in df.columns:
            present = df[col].notna()
            num = num + df[col].fillna(0) * w * present
            den = den + w * present
        else:
            den = den + w
    return (num / den.where(den > 0)).fillna(0.0)


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
    # Cut on `rank` (always unique, 1..n) rather than `hpm_index` (which can
    # have ties) so duplicates="drop" never collapses the bin count below
    # len(TIERS) and raises. With fewer malls than tiers, shrink the label
    # set instead of crashing.
    n_bins = min(4, df["rank"].nunique())
    # rank=1 is the best mall, so bins of ascending rank get labels in
    # descending tier order (best rank -> Platinum, worst rank -> Bronze).
    tier_labels = list(reversed(TIERS))[:n_bins]
    if n_bins:
        df["tier"] = pd.qcut(df["rank"], q=n_bins, labels=tier_labels, duplicates="drop")
    else:
        df["tier"] = pd.Series(dtype=object)
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


# --- robustness: how much does the ranking depend on the weights? ------------

def _block_matrix(df: pd.DataFrame, cols: list[str], W: np.ndarray) -> np.ndarray:
    """Weighted block scores for many weight vectors at once. W is (len(cols),
    n_draws). NaN scores drop out per mall exactly as in `_weighted_sum`."""
    X = df[cols].to_numpy(dtype=float)
    present = ~np.isnan(X)
    num = np.nan_to_num(X) @ W
    den = present.astype(float) @ W
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), 0.0)


def rank_stability(
    category_scores: pd.DataFrame,
    n_draws: int = 500,
    seed: int = 7,
    concentration: float = 60.0,
    supply_block_range: tuple[float, float] = (60.0, 80.0),
) -> pd.DataFrame:
    """Re-rank every mall under `n_draws` randomly perturbed weightings and
    report how stable each rank is. Supply and Demand sub-weights are drawn
    from Dirichlet distributions centred on the defaults (higher
    `concentration` = tighter), and the Supply share of the index is drawn
    uniformly from `supply_block_range`. Columns: default_rank, median_rank,
    rank_p5/p95 (the 5th/95th percentile rank), pct_top10/20/50 (share of
    draws in which the mall makes that shortlist)."""
    rng = np.random.default_rng(seed)
    s_cols, d_cols = list(DEFAULT_SUPPLY_WEIGHTS), list(DEFAULT_DEMAND_WEIGHTS)
    s0 = np.array(list(DEFAULT_SUPPLY_WEIGHTS.values()), dtype=float)
    d0 = np.array(list(DEFAULT_DEMAND_WEIGHTS.values()), dtype=float)
    Ws = rng.dirichlet(concentration * s0 / s0.sum(), size=n_draws).T
    Wd = rng.dirichlet(concentration * d0 / d0.sum(), size=n_draws).T
    block = rng.uniform(*supply_block_range, size=n_draws) / 100.0

    supply = _block_matrix(category_scores, s_cols, Ws)
    demand = _block_matrix(category_scores, d_cols, Wd)
    index = supply * block + demand * (1.0 - block)            # (malls, draws)
    ranks = (-index).argsort(axis=0).argsort(axis=0) + 1

    base = compute_index(category_scores)[["mall_id", "name", "rank"]].rename(columns={"rank": "default_rank"})
    order = category_scores.reset_index(drop=True)[["mall_id"]]
    out = order.merge(base, on="mall_id", how="left")
    out["median_rank"] = np.median(ranks, axis=1)
    out["rank_p5"] = np.percentile(ranks, 5, axis=1)
    out["rank_p95"] = np.percentile(ranks, 95, axis=1)
    for n in (10, 20, 50):
        out[f"pct_top{n}"] = (ranks <= n).mean(axis=1) * 100
    return out.sort_values("default_rank").reset_index(drop=True)


def _rank_corr(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank()))


def scenario_comparison(category_scores: pd.DataFrame) -> pd.DataFrame:
    """How different would the shortlist be under other defensible readings of
    the charter's weights? Each scenario is compared with the default ranking:
    `top10_overlap` is how many of its Top 10 are also in the default Top 10,
    `rank_corr` the Spearman correlation of the two index scores.

    The charter is ambiguous: its category weights (25/20/15/10/10/10 + Demand
    Potential 10) sum to 100 with Supply at 90%, yet its composite formula says
    Supply 70% / Demand 30%. "charter_literal" follows the first reading."""
    base = compute_index(category_scores)
    base_top = set(base.nsmallest(10, "rank")["mall_id"])
    scenarios = {
        "Default (70/30, proxies down-weighted)": {},
        "Charter category weights, 70/30": {"supply_weights": CHARTER_SUPPLY_WEIGHTS},
        "Proxy categories (C, F) excluded": {"supply_weights": exclude_proxies(DEFAULT_SUPPLY_WEIGHTS)},
        "Charter weights read literally (Supply 90 / Demand 10)": {
            "supply_weights": CHARTER_SUPPLY_WEIGHTS, "supply_block_weight": 90, "demand_block_weight": 10},
        "All six Supply categories equal": {"supply_weights": {k: 1 for k in CHARTER_SUPPLY_WEIGHTS}},
        "Supply only (ignore Demand)": {"supply_block_weight": 100, "demand_block_weight": 0},
    }
    rows = []
    for label, kwargs in scenarios.items():
        alt = compute_index(category_scores, **kwargs)
        merged = base[["mall_id", "hpm_index"]].merge(alt[["mall_id", "hpm_index"]], on="mall_id", suffixes=("", "_alt"))
        rows.append({
            "Scenario": label,
            "Top-10 overlap with default": len(base_top & set(alt.nsmallest(10, "rank")["mall_id"])),
            "Rank correlation with default": round(_rank_corr(merged["hpm_index"], merged["hpm_index_alt"]), 3),
        })
    return pd.DataFrame(rows)


def hpm_backtest(index_df: pd.DataFrame) -> dict | None:
    """Do HPB's existing Health Promoting Malls rank higher than the rest?
    Needs `is_existing_hpm` (from data/manual/existing_hpm.csv). Returns None
    when no mall is flagged (or all are). AUC is the probability that a
    randomly chosen existing HPM scores higher than a randomly chosen other
    mall (0.5 = no better than chance, 1.0 = perfect separation)."""
    if "is_existing_hpm" not in index_df.columns:
        return None
    flag = index_df["is_existing_hpm"].fillna(0).astype(int) == 1
    n1, n0 = int(flag.sum()), int((~flag).sum())
    if n1 == 0 or n0 == 0:
        return None
    ranks = index_df["hpm_index"].rank()                       # ascending: best = highest
    auc = (ranks[flag].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    n = len(index_df)
    return {
        "n_existing_hpm": n1,
        "median_rank": float(index_df.loc[flag, "rank"].median()),
        "mean_percentile": float((1 - (index_df.loc[flag, "rank"] - 1) / max(n - 1, 1)).mean() * 100),
        "in_top20": int((index_df.loc[flag, "rank"] <= 20).sum()),
        "in_top50": int((index_df.loc[flag, "rank"] <= 50).sum()),
        "auc": float(auc),
    }
