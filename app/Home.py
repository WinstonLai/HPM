"""Page 1 - Executive Summary.

Streamlit entrypoint: `streamlit run app/Home.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402
import weights  # noqa: E402
from safe_text import escape_html  # noqa: E402

st.set_page_config(page_title="HPM Readiness Dashboard", page_icon="🛍️", layout="wide")

st.title("🛍️ Health Promoting Mall (HPM) Readiness Dashboard")
st.caption(
    "HPB Health Promoting Town initiative · Executive Summary · "
    "data pulled from data.gov.sg, OneMap and Wikipedia — see the README for full source citations."
)

if not data_loader.data_available():
    st.error(
        "No processed data found. Run `python etl/run_all.py` first to build "
        "data/processed/category_scores.csv and hpm_index.csv."
    )
    st.stop()

df, is_custom = weights.load_index()
weights.show_banner("home")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total malls assessed", len(df))
col2.metric("Average HPM Index", f"{df['hpm_index'].mean():.1f} / 100")
col3.metric("Malls in Gold/Platinum tier", int(df["tier"].isin(["Gold", "Platinum"]).sum()),
            help=f"Tiers use fixed cut-offs (Platinum ≥ {scoring.TIER_THRESHOLDS['Platinum']:.0f}, "
                 f"Gold ≥ {scoring.TIER_THRESHOLDS['Gold']:.0f}, Silver ≥ {scoring.TIER_THRESHOLDS['Silver']:.0f}), "
                 "so this count moves when the weights or mall list change.")
if "is_existing_hpm" in df.columns and int(df["is_existing_hpm"].sum()) > 0:
    n_top = int(df.loc[df["rank"] <= 20, "is_existing_hpm"].sum())
    col4.metric("Existing HPMs in the Top 20", f"{n_top} of 20",
                help="How many of the 20 highest-ranked malls HPB has already designated as HPMs.")
else:
    col4.metric("Regions covered", df["region"].nunique())

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("Top 10 Malls")
    top10 = df.sort_values("hpm_index", ascending=False).head(10)
    st.dataframe(
        top10[["rank", "name", "region", "operator", "hpm_index", "tier"]]
        .rename(columns={"name": "Mall", "region": "Region", "operator": "Operator",
                          "hpm_index": "HPM Index", "tier": "Tier", "rank": "Rank"})
        .style.format({"HPM Index": "{:.1f}"}),
        hide_index=True,
        use_container_width=True,
    )

with right:
    st.subheader("Malls by Region")
    region_counts = df["region"].value_counts().reset_index()
    region_counts.columns = ["Region", "Malls"]
    fig = px.bar(region_counts, x="Region", y="Malls", color="Region")
    fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0), height=300)
    st.plotly_chart(fig, use_container_width=True)

st.divider()

st.subheader("Top Landlords / Operators")
op_summary = (
    df[df["operator"] != "Unknown"]
    .groupby("operator")
    .agg(malls=("name", "count"), avg_index=("hpm_index", "mean"))
    .sort_values("malls", ascending=False)
    .head(10)
    .reset_index()
)
op_summary["operator"] = op_summary["operator"].map(escape_html)    # Plotly axis labels are pseudo-HTML
if op_summary.empty:
    st.info("No operator data could be resolved from Wikipedia infoboxes for this run.")
else:
    fig2 = px.bar(
        op_summary,
        x="operator",
        y="malls",
        color="avg_index",
        color_continuous_scale="Tealgrn",
        labels={"operator": "Operator", "malls": "Number of Malls", "avg_index": "Avg HPM Index"},
    )
    fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=350)
    st.plotly_chart(fig2, use_container_width=True)
    st.caption(
        "Operator identified via each mall's Wikipedia infobox (owner/developer/management field); "
        "malls with no resolvable field are excluded here and labelled 'Unknown' elsewhere."
    )

st.divider()
st.info(
    "**New here?** The **Methodology** page (left sidebar) explains where this data comes "
    "from and walks through exactly how any mall's score is calculated, with a real example.",
    icon="📖",
)
meta = data_loader.load_meta()
if meta:
    built = meta.get("category_scores", {}).get("built_at", "")[:10]
    st.caption(
        f"Data built {built or 'on an unknown date'} · {len(df)} malls · "
        "population and workers: Census 2020 · other layers fetched "
        f"{meta.get('raw_data', {}).get('latest_fetch', 'on an unknown date')[:10]}. "
        "Details in data/processed/_meta.json."
    )
st.caption(
    "Use the pages in the left sidebar: National Ranking, What-If Simulator, Mall Comparison, "
    "National Map, Strategic Matrix, Methodology, and Regional Priorities."
)
