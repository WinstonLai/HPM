"""Page 4 - Mall Comparison: up to 5 malls, radar chart, strengths/weaknesses."""
from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402

st.set_page_config(page_title="Mall Comparison | HPM Dashboard", page_icon="🕸️", layout="wide")
st.title("🕸️ Mall Comparison")

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df = data_loader.load_default_index()
RADAR_COLS = list(scoring.DEFAULT_SUPPLY_WEIGHTS.keys()) + list(scoring.DEFAULT_DEMAND_WEIGHTS.keys())

names = st.multiselect(
    "Select up to 5 malls to compare",
    sorted(df["name"]),
    default=list(df.sort_values("hpm_index", ascending=False)["name"].head(3)),
    max_selections=5,
)

if not names:
    st.info("Pick at least one mall above.")
    st.stop()

subset = df[df["name"].isin(names)].set_index("name")

fig = go.Figure()
for name in names:
    row = subset.loc[name]
    values = [row[c] for c in RADAR_COLS]
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=[scoring.CATEGORY_LABELS[c] for c in RADAR_COLS] + [scoring.CATEGORY_LABELS[RADAR_COLS[0]]],
        fill="toself",
        name=name,
    ))
fig.update_layout(
    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
    height=550,
    legend=dict(orientation="h", yanchor="bottom", y=-0.15),
)
st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("Strengths and weaknesses")
cols = st.columns(len(names))
for col, name in zip(cols, names):
    row = subset.loc[name]
    scores = {scoring.CATEGORY_LABELS[c]: row[c] for c in RADAR_COLS}
    best = max(scores, key=scores.get)
    worst = min(scores, key=scores.get)
    with col:
        st.markdown(f"**{name}**")
        st.metric("HPM Index", f"{row['hpm_index']:.1f}", help=f"Tier: {row['tier']}")
        st.success(f"Strongest: {best} ({scores[best]:.0f})")
        st.warning(f"Weakest: {worst} ({scores[worst]:.0f})")
