"""Page 6 - Strategic Matrix (enhancement): 2x2 Readiness x Demand quadrant view."""
from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402

st.set_page_config(page_title="Strategic Matrix | HPM Dashboard", page_icon="🧭", layout="wide")
st.title("🧭 Strategic Matrix")
st.caption(
    "Readiness (Supply Score) vs Demand (Demand Opportunity Score), split at the median of each axis — "
    "the charter's proposed enhancement over a flat ranked list for leadership discussions."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df = data_loader.load_default_index()
df = scoring.add_strategic_quadrant(df)

QUADRANT_COLORS = {
    "Pioneer HPM": "#1a9850",
    "Quick Wins": "#66bd63",
    "Strategic Investment": "#fdae61",
    "Future Monitoring": "#d73027",
}

fig = px.scatter(
    df,
    x="demand_score",
    y="supply_score",
    color="quadrant",
    color_discrete_map=QUADRANT_COLORS,
    hover_name="name",
    hover_data={"region": True, "operator": True, "demand_score": ":.1f", "supply_score": ":.1f"},
    labels={"demand_score": "Demand Opportunity Score", "supply_score": "Supply Readiness Score"},
)
fig.add_vline(x=df["demand_score"].median(), line_dash="dash", line_color="gray")
fig.add_hline(y=df["supply_score"].median(), line_dash="dash", line_color="gray")
fig.update_layout(height=650, legend=dict(orientation="h", yanchor="bottom", y=-0.2))
st.plotly_chart(fig, use_container_width=True)

st.divider()
cols = st.columns(4)
descriptions = {
    "Pioneer HPM": "High readiness + high demand -> ready for immediate deployment.",
    "Quick Wins": "High readiness + low demand -> low-effort expansion.",
    "Strategic Investment": "Low readiness + high demand -> high-impact opportunities needing capability building.",
    "Future Monitoring": "Low readiness + low demand -> not immediate priorities.",
}
for col, (quadrant, desc) in zip(cols, descriptions.items()):
    with col:
        count = int((df["quadrant"] == quadrant).sum())
        st.metric(quadrant, count)
        st.caption(desc)

st.divider()
selected_quadrant = st.selectbox("Drill into a quadrant", list(descriptions.keys()))
subset = df[df["quadrant"] == selected_quadrant].sort_values("hpm_index", ascending=False)
st.dataframe(
    subset[["rank", "name", "region", "operator", "supply_score", "demand_score", "hpm_index"]]
    .rename(columns={"rank": "Rank", "name": "Mall", "region": "Region", "operator": "Operator",
                      "supply_score": "Supply", "demand_score": "Demand", "hpm_index": "HPM Index"})
    .style.format({"Supply": "{:.1f}", "Demand": "{:.1f}", "HPM Index": "{:.1f}"}),
    hide_index=True,
    use_container_width=True,
)
