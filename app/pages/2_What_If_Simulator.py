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

with st.sidebar:
    st.header("Supply Readiness weights")
    st.caption("Relative weights within Supply (auto-normalised to 100%).")
    supply_weights = {}
    for col, default in scoring.DEFAULT_SUPPLY_WEIGHTS.items():
        label = scoring.CATEGORY_LABELS[col]
        supply_weights[col] = st.slider(label, 0, 100, int(round(default)), key=f"sw_{col}")

    st.header("Demand Opportunity weights")
    demand_weights = {}
    for col, default in scoring.DEFAULT_DEMAND_WEIGHTS.items():
        label = scoring.CATEGORY_LABELS[col]
        demand_weights[col] = st.slider(label, 0, 100, int(round(default)), key=f"dw_{col}")

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
