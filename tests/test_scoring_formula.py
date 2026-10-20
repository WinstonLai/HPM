import numpy as np
import pandas as pd
import pytest

import scoring_formula as sf

SCORE_COLS = list(sf.CATEGORY_LABELS)


def make_scores(n=40, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(rng.uniform(0, 100, (n, len(SCORE_COLS))), columns=SCORE_COLS)
    df.insert(0, "name", [f"Mall {i}" for i in range(n)])
    df.insert(0, "mall_id", [f"mall-{i}" for i in range(n)])
    return df


def test_default_supply_weights_sum_to_100_and_proxies_are_down_weighted():
    assert sum(sf.DEFAULT_SUPPLY_WEIGHTS.values()) == pytest.approx(100)
    assert sf.DEFAULT_SUPPLY_WEIGHTS["C_engagement_score"] < sf.CHARTER_SUPPLY_WEIGHTS["C_engagement_score"] / 90 * 100
    assert sf.DEFAULT_SUPPLY_WEIGHTS["F_partnership_score"] < sf.CHARTER_SUPPLY_WEIGHTS["F_partnership_score"] / 90 * 100


def test_compute_index_ranks_are_unique_and_sorted():
    r = sf.compute_index(make_scores())
    assert r["rank"].tolist() == list(range(1, len(r) + 1))
    assert r["hpm_index"].is_monotonic_decreasing


def test_index_is_70_30_blend_of_blocks():
    r = sf.compute_index(make_scores())
    expected = r["supply_score"] * 0.7 + r["demand_score"] * 0.3
    assert np.allclose(r["hpm_index"], expected)


def test_tiers_use_absolute_cutoffs_and_move_with_the_scores():
    idx = pd.Series([60.0, 50.0, 49.9, 35.0, 34.9, 20.0, 19.9, 0.0])
    assert sf.assign_tiers(idx).astype(str).tolist() == [
        "Platinum", "Platinum", "Gold", "Gold", "Silver", "Silver", "Bronze", "Bronze"]
    strict = sf.assign_tiers(idx, {"Platinum": 80, "Gold": 60, "Silver": 40}).astype(str).tolist()
    assert strict.count("Platinum") == 0              # nothing is forced into a tier


def test_a_nan_factor_is_dropped_and_the_rest_reweighted():
    df = make_scores(5)
    df.loc[0, "engagement_gap_score"] = np.nan
    r = sf.compute_index(df).set_index("mall_id")
    w = sf.DEFAULT_DEMAND_WEIGHTS
    row = df.loc[0]
    expect = (row["reach_population_score"] * w["reach_population_score"]
              + row["accessibility_score"] * w["accessibility_score"]) / (
        w["reach_population_score"] + w["accessibility_score"])
    assert r.loc["mall-0", "demand_score"] == pytest.approx(expect)


def test_exclude_proxies_zeroes_only_c_and_f():
    w = sf.exclude_proxies(sf.DEFAULT_SUPPLY_WEIGHTS)
    assert w["C_engagement_score"] == 0 and w["F_partnership_score"] == 0
    assert w["A_dining_score"] == sf.DEFAULT_SUPPLY_WEIGHTS["A_dining_score"]
    df = make_scores(10)
    base = sf.compute_index(df, supply_weights=w).set_index("mall_id")["supply_score"]
    df2 = df.assign(C_engagement_score=0.0, F_partnership_score=0.0)
    again = sf.compute_index(df2, supply_weights=w).set_index("mall_id")["supply_score"]
    assert np.allclose(base.sort_index(), again.sort_index())     # proxies no longer matter


def test_strategic_quadrant_uses_median_by_default_and_fixed_cuts_on_request():
    df = sf.compute_index(make_scores(41))
    med = sf.add_strategic_quadrant(df)
    assert 0.4 < med["supply_high"].mean() < 0.62
    fixed = sf.add_strategic_quadrant(df, supply_cut=101, demand_cut=101)
    assert (fixed["quadrant"] == "Future Monitoring").all()
    assert set(med["quadrant"]) <= {"Pioneer HPM", "Quick Wins", "Strategic Investment", "Future Monitoring"}


def test_rank_stability_is_deterministic_and_bounded():
    df = make_scores(30)
    a = sf.rank_stability(df, n_draws=50, seed=3)
    b = sf.rank_stability(df, n_draws=50, seed=3)
    pd.testing.assert_frame_equal(a, b)
    assert a[["pct_top10", "pct_top20", "pct_top50"]].stack().between(0, 100).all()
    assert (a["rank_p5"] <= a["median_rank"]).all() and (a["median_rank"] <= a["rank_p95"]).all()


def test_a_dominant_mall_stays_first_under_any_weights():
    df = make_scores(30).copy()
    df.loc[0, SCORE_COLS] = 100.0
    df.loc[1:, SCORE_COLS] = df.loc[1:, SCORE_COLS] * 0.5
    r = sf.rank_stability(df, n_draws=100)
    assert r.iloc[0]["name"] == "Mall 0" and r.iloc[0]["rank_p95"] == 1


def test_rank_stability_can_be_centred_on_custom_weights():
    df = make_scores(30)
    only_dining = {k: (100 if k == "A_dining_score" else 0) for k in sf.DEFAULT_SUPPLY_WEIGHTS}
    r = sf.rank_stability(df, n_draws=80, supply_weights=only_dining, supply_block_weight=100)
    expect = df.sort_values("A_dining_score", ascending=False)["name"].iloc[0]
    assert r.iloc[0]["name"] == expect                    # default_rank reflects the custom weights


def test_scenario_comparison_default_row_is_identical():
    out = sf.scenario_comparison(make_scores(40))
    first = out.iloc[0]
    assert first["Top-10 overlap with default"] == 10 and first["Rank correlation with default"] == pytest.approx(1.0)
    assert len(out) >= 5


def test_backtest_needs_a_flag_and_scores_perfect_separation_as_auc_1():
    idx = sf.compute_index(make_scores(30))
    assert sf.hpm_backtest(idx) is None
    idx["is_existing_hpm"] = 0
    assert sf.hpm_backtest(idx) is None                   # nobody flagged
    idx.loc[idx["rank"] <= 5, "is_existing_hpm"] = 1
    result = sf.hpm_backtest(idx)
    assert result["auc"] == pytest.approx(1.0) and result["in_top20"] == 5
    idx["is_existing_hpm"] = 0
    idx.loc[idx["rank"] > 25, "is_existing_hpm"] = 1
    assert sf.hpm_backtest(idx)["auc"] == pytest.approx(0.0)
    assert sf.component_auc(idx)["hpm_index"] == pytest.approx(0.0)
