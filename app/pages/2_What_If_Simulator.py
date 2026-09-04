"""Page 3 - What-If Simulator: reweight categories live, ranking updates instantly."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402

st.set_page_config(page_title="What-If Simulator | HPM Dashboard", page_icon="🎚️", layout="wide")
st.title("🎚️ What-If Simulator")
st.caption(
    "Adjust category weights and the overall Supply/Demand split — the ranking, tiers, "
    "and Top 10/20/50 shortlists below recompute instantly."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

category_scores = data_loader.load_category_scores()


def _integerize_to_100(weights: dict) -> dict:
    """Largest-remainder rounding: convert arbitrary positive weights to
    integers that sum to exactly 100 (naive round() can drift, e.g. three
    equal 33.33s round to 99)."""
    keys = list(weights.keys())
    total = sum(weights.values()) or 1.0
    scaled = [weights[k] / total * 100 for k in keys]
    floors = [int(x) for x in scaled]
    remainder = 100 - sum(floors)
    order = sorted(range(len(keys)), key=lambda i: scaled[i] - floors[i], reverse=True)
    for i in range(remainder):
        floors[order[i]] += 1
    return {keys[i]: floors[i] for i in range(len(keys))}


def _rebalance(changed_key: str, group_keys: list[str]) -> None:
    """on_change callback: keep a slider group summing to exactly 100 by
    redistributing the remaining budget across the other sliders in the
    group, proportional to their current relative weights."""
    new_val = st.session_state[changed_key]
    others = [k for k in group_keys if k != changed_key]
    remaining = 100 - new_val
    others_sum = sum(st.session_state[k] for k in others)

    allocated = 0
    for k in others[:-1]:
        share = round(st.session_state[k] / others_sum * remaining) if others_sum > 0 else remaining // len(others)
        share = max(0, min(remaining - allocated, share))
        st.session_state[k] = share
        allocated += share
    st.session_state[others[-1]] = max(0, remaining - allocated)


def linked_weight_sliders(group_keys: list[str], defaults: dict, key_prefix: str) -> dict:
    """Render a group of sliders that always sum to 100: moving one
    proportionally redistributes the remaining budget across the rest."""
    session_keys = [f"{key_prefix}_{col}" for col in group_keys]
    if session_keys[0] not in st.session_state:
        initial = _integerize_to_100(defaults)
        for col, skey in zip(group_keys, session_keys):
            st.session_state[skey] = initial[col]

    weights = {}
    for col, skey in zip(group_keys, session_keys):
        st.slider(
            scoring.CATEGORY_LABELS[col], 0, 100, key=skey,
            on_change=_rebalance, args=(skey, session_keys),
        )
        weights[col] = st.session_state[skey]
    return weights


with st.sidebar:
    st.header("Supply Readiness weights")
    st.caption("Sliders are linked and always sum to 100% — raising one lowers the rest proportionally.")
    supply_weights = linked_weight_sliders(
        list(scoring.DEFAULT_SUPPLY_WEIGHTS.keys()), scoring.DEFAULT_SUPPLY_WEIGHTS, "sw"
    )

    st.header("Demand Opportunity weights")
    st.caption("Also linked, summing to 100%.")
    demand_weights = linked_weight_sliders(
        list(scoring.DEFAULT_DEMAND_WEIGHTS.keys()), scoring.DEFAULT_DEMAND_WEIGHTS, "dw"
    )

    st.header("Overall split")
    supply_block_weight = st.slider("Supply Readiness weight (%)", 0, 100, 70)
    demand_block_weight = 100 - supply_block_weight
    st.caption(f"Demand Opportunity weight: **{demand_block_weight}%**")

result = scoring.compute_index(
    category_scores,
    supply_weights=supply_weights,
    demand_weights=demand_weights,
    supply_block_weight=supply_block_weight,
    demand_block_weight=demand_block_weight,
)

col1, col2, col3 = st.columns(3)
col1.metric("Top 10 cutoff score", f"{result.nsmallest(10, 'rank')['hpm_index'].min():.1f}")
col2.metric("Top 20 cutoff score", f"{result.nsmallest(20, 'rank')['hpm_index'].min():.1f}")
col3.metric("Top 50 cutoff score", f"{result.nsmallest(50, 'rank')['hpm_index'].min():.1f}")

tab1, tab2, tab3 = st.tabs(["Top 10", "Top 20", "Top 50"])
display_cols = ["rank", "name", "region", "operator", "hpm_index", "tier"]
rename = {"rank": "Rank", "name": "Mall", "region": "Region", "operator": "Operator",
          "hpm_index": "Score", "tier": "Tier"}

for tab, n in zip((tab1, tab2, tab3), (10, 20, 50)):
    with tab:
        shortlist = result.nsmallest(n, "rank")[display_cols].rename(columns=rename)
        st.dataframe(
            shortlist.style.format({"Score": "{:.1f}"}),
            hide_index=True,
            use_container_width=True,
            height=min(38 * (n + 1), 700),
        )
