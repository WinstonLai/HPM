"""Mall Comparison: up to 5 malls, radar chart, strengths/weaknesses."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402
import weights  # noqa: E402
from safe_text import escape_html, escape_md  # noqa: E402

st.set_page_config(page_title="Mall Comparison | HPM Dashboard", page_icon="🕸️", layout="wide")
st.title("🕸️ Mall Comparison")

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df, is_custom = weights.load_index()
weights.show_banner("comparison")
RADAR_COLS = list(scoring.DEFAULT_SUPPLY_WEIGHTS.keys()) + list(scoring.DEFAULT_DEMAND_WEIGHTS.keys())
LABELS = scoring.CATEGORY_LABELS
PROXIES = set(scoring.PROXY_CATEGORIES)

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
median = df[RADAR_COLS].median()
theta = [LABELS[c] for c in RADAR_COLS]

fig = go.Figure()
fig.add_trace(go.Scatterpolar(
    r=list(median.values) + [median.values[0]], theta=theta + [theta[0]],
    name="All-mall median", line=dict(color="gray", dash="dot"), fill=None,
))
for name in names:
    row = subset.loc[name]
    values = [None if pd.isna(row[c]) else row[c] for c in RADAR_COLS]  # n/a factors leave a gap
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]], theta=theta + [theta[0]], fill="toself", opacity=0.55, name=escape_html(name),
    ))
fig.update_layout(
    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
    height=550,
    legend=dict(orientation="h", yanchor="bottom", y=-0.15),
)
st.plotly_chart(fig, width="stretch")
st.caption("The dotted grey line is the median mall: a score outside it is better than the typical mall.")

st.divider()
st.subheader("Strengths and weaknesses")
st.caption(
    "Compared with **all malls** (percentile among the "
    f"{len(df)}), not on the raw 0–100 score — most malls score 0 on some categories, so \"lowest score\" says little. "
    "The two proxy categories (H365 & HPB Engagement, Partnership Readiness) are left out of the verdicts "
    "because they are stand-ins, not real measurements."
)
percentile = df[RADAR_COLS].rank(pct=True) * 100
percentile.index = df["name"]
cols = st.columns(len(names))
for col, name in zip(cols, names):
    row = subset.loc[name]
    pct = percentile.loc[name]
    eligible = {c: pct[c] for c in RADAR_COLS if c not in PROXIES and pd.notna(row[c])}
    best = max(eligible, key=eligible.get)
    worst = min(eligible, key=eligible.get)
    with col:
        st.markdown(f"**{escape_md(name)}**")
        st.metric("HPM Index", f"{row['hpm_index']:.1f}", help=f"Rank {int(row['rank'])} · Tier: {row['tier']}")
        st.success(f"Strongest: {LABELS[best]} — better than {eligible[best]:.0f}% of malls")
        st.warning(f"Weakest: {LABELS[worst]} — better than {eligible[worst]:.0f}% of malls")

st.divider()
st.subheader("What's behind the scores")
RAW = {
    "Healthier dining outlets + supermarkets": "A_dining_count",
    "Gyms / sports facilities (200m)": "B_fitness_count",
    "Community clubs (500m, proxy)": "C_engagement_count",
    "Clinics + pharmacies": "D_healthcare_count",
    "Parks / playgrounds / water points (500m + bike racks)": "E_infra_count",
    "Residents (distance-weighted, ~2km)": "pop_reach_weighted",
    "Seniors 65+ (distance-weighted)": "senior_reach_weighted",
    "Workers (distance-weighted)": "worker_reach_weighted",
    "MRT stations within 1.2km": "mrt_count",
    "Nearest MRT station (m)": "mrt_nearest_m",
    "Bus stops within 400m": "bus_count",
}
# Every cell is text so the table has one type per column (a "Landlord" row of words next
# to rows of numbers cannot be converted by Streamlit's Arrow layer).
raw = pd.DataFrame({label: subset.loc[names, col].map("{:,.0f}".format)
                    for label, col in RAW.items() if col in subset.columns}).T
raw.columns = names
raw.loc["Landlord"] = subset.loc[names, "operator"].values
st.dataframe(raw, width="stretch")
st.caption("The raw numbers each 0–100 score is built from. Counts are for the whole mall's surroundings, "
           "not a per-store measure.")
