"""Single source of truth for the composite Health Readiness Index formula:

    Health Readiness Index = Supply Readiness (70%) + Demand Opportunity (30%)
    Supply Readiness  = Dining + Fitness + Community Engagement + Healthcare
                         + Infrastructure + Partnership Readiness
    Demand Opportunity = Reach & Population + Accessibility + Engagement Gap

The per-category reference weights (A 25%, B 20%, C 15%,
D 10%, E 10%, F 10% -- these six sum to 90, not 100, in the original specification)
are renormalised to sum to 100 *within* Supply Readiness, since Supply itself
is only 70% of the final index and Category G ("Demand Potential") is
represented by the separate Reach/Accessibility/Engagement-Gap block rather
than as a seventh flat weight.

Categories C (Community Engagement) and F (Partnership Readiness) are
PROXIES -- no public dataset measures the real thing -- and are coarse (C only
takes the values 0/50/100; F is non-zero for only a handful of malls). They
therefore start below the reference weights (C 15 -> 10,
F 10 -> 5), and can be switched off entirely on the What-If Simulator via
`exclude_proxies`. The reference values are kept in REFERENCE_SUPPLY_WEIGHTS.

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
# The original reference weights, for reference / the Methodology page.
REFERENCE_SUPPLY_WEIGHTS = {
    "A_dining_score": 25,
    "B_fitness_score": 20,
    "C_engagement_score": 15,   # community engagement in the composite formula
    "D_healthcare_score": 10,
    "E_infra_score": 10,
    "F_partnership_score": 10,
}
# Categories scored with a proxy rather than the metric their names suggest.
PROXY_CATEGORIES = ("C_engagement_score", "F_partnership_score")
_RAW_SUPPLY_WEIGHTS = {
    "A_dining_score": 25,
    "B_fitness_score": 20,
    "C_engagement_score": 10,   # proxy (community-club proximity): reference 15
    "D_healthcare_score": 10,
    "E_infra_score": 10,
    "F_partnership_score": 5,   # proxy (landlord portfolio size): reference 10
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
    "C_engagement_score": "Community Engagement",
    "D_healthcare_score": "Healthcare",
    "E_infra_score": "Healthy Infrastructure",
    "F_partnership_score": "Partnership Readiness",
    "reach_population_score": "Reach & Population",
    "accessibility_score": "Accessibility",
    "engagement_gap_score": "Engagement Gap",
}

TIERS = ["Bronze", "Silver", "Gold", "Platinum"]

# Minimum Health Readiness Index for each tier; anything below Silver is Bronze. Absolute
# bands (not rank quartiles), so a tier count can actually change when the
# weights or the mall list change. The index is itself relative -- every
# category is scaled against the best malls in this list -- so these cut-offs
# say "high within this list", not "certified ready". They are a judgement
# call; the What-If Simulator lets users move them.
TIER_THRESHOLDS = {"Platinum": 50.0, "Gold": 35.0, "Silver": 20.0}


def assign_tiers(index: pd.Series, thresholds: dict | None = None) -> pd.Series:
    """Bronze/Silver/Gold/Platinum from absolute Health Readiness Index cut-offs. Tied or
    out-of-order cut-offs are allowed (the higher tier just goes unused)
    instead of raising, since the What-If Simulator lets users drag them."""
    t = thresholds or TIER_THRESHOLDS
    silver, gold, platinum = np.maximum.accumulate([t["Silver"], t["Gold"], t["Platinum"]])
    codes = (index >= silver).astype(int) + (index >= gold) + (index >= platinum)
    return pd.Series(pd.Categorical.from_codes(codes.where(index.notna(), -1), categories=TIERS),
                     index=index.index)


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
    tier_thresholds: dict | None = None,
) -> pd.DataFrame:
    """Return a copy of `category_scores` with supply_score, demand_score,
    hpm_index, rank, and tier columns computed from the given weights
    (falling back to the reference defaults). Tiers use
    absolute cut-offs (`tier_thresholds`, default TIER_THRESHOLDS)."""
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
    df["tier"] = assign_tiers(df["hpm_index"], tier_thresholds)
    n = len(df)
    df["top10"] = df["rank"] <= min(10, n)
    df["top20"] = df["rank"] <= min(20, n)
    df["top50"] = df["rank"] <= min(50, n)
    return df


def strategic_quadrant(row) -> str:
    """2x2 matrix of readiness vs demand:
    High Readiness + High Demand -> Pioneer
    High Readiness + Low Demand  -> Quick Wins
    Low Readiness  + High Demand -> Strategic Investment
    Low Readiness  + Low Demand  -> Future Monitoring
    """
    high_supply = row["supply_high"]
    high_demand = row["demand_high"]
    if high_supply and high_demand:
        return "Pioneer"
    if high_supply and not high_demand:
        return "Quick Wins"
    if not high_supply and high_demand:
        return "Strategic Investment"
    return "Future Monitoring"


def add_strategic_quadrant(df: pd.DataFrame, supply_cut: float | None = None,
                           demand_cut: float | None = None) -> pd.DataFrame:
    """Assign the 2x2 quadrant. A mall is "high" on an axis when its score is at
    or above the cut-off, which defaults to that axis's median -- so by default
    about half of all malls are "high" on each axis however low the scores are.
    Pass absolute `supply_cut` / `demand_cut` for a fixed bar instead."""
    df = df.copy()
    supply_med = df["supply_score"].median() if supply_cut is None else supply_cut
    demand_med = df["demand_score"].median() if demand_cut is None else demand_cut
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
    supply_weights: dict | None = None,
    demand_weights: dict | None = None,
    supply_block_weight: float | None = None,
) -> pd.DataFrame:
    """Re-rank every mall under `n_draws` randomly perturbed weightings and
    report how stable each rank is. Supply and Demand sub-weights are drawn
    from Dirichlet distributions centred on the defaults (higher
    `concentration` = tighter), and the Supply share of the index is drawn
    uniformly from `supply_block_range`. Columns: default_rank, median_rank,
    rank_p5/p95 (the 5th/95th percentile rank), pct_top10/20/50 (share of
    draws in which the mall makes that shortlist).

    By default the draws are centred on the default weights; pass
    `supply_weights` / `demand_weights` / `supply_block_weight` to centre them
    on a custom weighting (the Supply share then varies +/-10 points around
    it), so the What-If Simulator can show how fragile *its* shortlist is."""
    rng = np.random.default_rng(seed)
    supply_weights = supply_weights or DEFAULT_SUPPLY_WEIGHTS
    demand_weights = demand_weights or DEFAULT_DEMAND_WEIGHTS
    s_cols, d_cols = list(supply_weights), list(demand_weights)
    s0 = np.maximum(np.array(list(supply_weights.values()), dtype=float), 1e-3)
    d0 = np.maximum(np.array(list(demand_weights.values()), dtype=float), 1e-3)
    if supply_block_weight is not None:
        supply_block_range = (max(0.0, supply_block_weight - 10.0), min(100.0, supply_block_weight + 10.0))
    Ws = rng.dirichlet(concentration * s0 / s0.sum(), size=n_draws).T
    Wd = rng.dirichlet(concentration * d0 / d0.sum(), size=n_draws).T
    block = rng.uniform(*supply_block_range, size=n_draws) / 100.0

    supply = _block_matrix(category_scores, s_cols, Ws)
    demand = _block_matrix(category_scores, d_cols, Wd)
    index = supply * block + demand * (1.0 - block)            # (malls, draws)
    ranks = (-index).argsort(axis=0).argsort(axis=0) + 1

    base = compute_index(
        category_scores, supply_weights=supply_weights, demand_weights=demand_weights,
        supply_block_weight=SUPPLY_BLOCK_WEIGHT if supply_block_weight is None else supply_block_weight,
        demand_block_weight=DEMAND_BLOCK_WEIGHT if supply_block_weight is None else 100 - supply_block_weight,
    )[["mall_id", "name", "rank"]].rename(columns={"rank": "default_rank"})
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
    the reference weights? Each scenario is compared with the default ranking:
    `top10_overlap` is how many of its Top 10 are also in the default Top 10,
    `rank_corr` the Spearman correlation of the two index scores.

    The reference weights are ambiguous: the category weights (25/20/15/10/10/10 + Demand
    Potential 10) sum to 100 with Supply at 90%, yet its composite formula says
    Supply 70% / Demand 30%. "the literal reading" follows the first reading."""
    base = compute_index(category_scores)
    base_top = set(base.nsmallest(10, "rank")["mall_id"])
    scenarios = {
        "Default (70/30, proxies down-weighted)": {},
        "Reference category weights, 70/30": {"supply_weights": REFERENCE_SUPPLY_WEIGHTS},
        "Proxy categories (C, F) excluded": {"supply_weights": exclude_proxies(DEFAULT_SUPPLY_WEIGHTS)},
        "Reference weights read literally (Supply 90 / Demand 10)": {
            "supply_weights": REFERENCE_SUPPLY_WEIGHTS, "supply_block_weight": 90, "demand_block_weight": 10},
        "All six Supply categories equal": {"supply_weights": {k: 1 for k in REFERENCE_SUPPLY_WEIGHTS}},
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


def component_auc(index_df: pd.DataFrame) -> pd.Series:
    """AUC of each score column at separating reference malls from other malls
    (0.5 = no better than chance). Shows WHICH components make the index
    resemble the reference list. Read with care: Healthy Dining is built
    from the national Healthier Dining datasets, so reference malls scoring well on
    it is partly circular (designated malls likely already take part in those
    programmes) rather than evidence of predictive power."""
    flag = index_df["is_existing_hpm"].fillna(0).astype(int) == 1
    n1, n0 = int(flag.sum()), int((~flag).sum())
    cols = ["hpm_index", "supply_score", "demand_score", *CATEGORY_LABELS]
    out = {}
    for col in cols:
        if col in index_df.columns and n1 and n0:
            ranks = index_df[col].rank()
            out[col] = float((ranks[flag].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return pd.Series(out)


def hpm_backtest(index_df: pd.DataFrame) -> dict | None:
    """Do the reference malls rank higher than the rest?
    Needs `is_existing_hpm` (from data/manual/existing_hpm.csv). Returns None
    when no mall is flagged (or all are). AUC is the probability that a
    randomly chosen reference mall scores higher than a randomly chosen other
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
