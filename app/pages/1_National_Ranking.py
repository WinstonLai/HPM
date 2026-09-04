"""Page 2 - National Ranking: dynamic ranking table with region/operator/tier filters."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402

st.set_page_config(page_title="National Ranking | HPM Dashboard", page_icon="📋", layout="wide")
st.title("📋 National Ranking")

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df = data_loader.load_default_index()

with st.sidebar:
    st.header("Filters")
    regions = st.multiselect("Region", sorted(df["region"].unique()))
    operators = st.multiselect("Mall operator", sorted(df["operator"].unique()))
    tiers = st.multiselect("Readiness tier", ["Platinum", "Gold", "Silver", "Bronze"])

filtered = df.copy()
if regions:
    filtered = filtered[filtered["region"].isin(regions)]
if operators:
    filtered = filtered[filtered["operator"].isin(operators)]
if tiers:
    filtered = filtered[filtered["tier"].isin(tiers)]

st.caption(f"Showing {len(filtered)} of {len(df)} malls (default illustrative weights — "
           "adjust weights on the What-If Simulator page).")

st.dataframe(
    filtered[["rank", "name", "region", "operator", "hpm_index", "tier",
              "supply_score", "demand_score"]]
    .rename(columns={
        "rank": "Rank", "name": "Mall", "region": "Region", "operator": "Operator",
        "hpm_index": "Score", "tier": "Tier",
        "supply_score": "Supply Readiness", "demand_score": "Demand Opportunity",
    })
    .style.format({"Score": "{:.1f}", "Supply Readiness": "{:.1f}", "Demand Opportunity": "{:.1f}"}),
    hide_index=True,
    use_container_width=True,
    height=650,
)
