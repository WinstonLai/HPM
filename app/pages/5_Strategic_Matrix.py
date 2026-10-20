"""Page 6 - Strategic Matrix (enhancement): 2x2 Readiness x Demand quadrant view."""
from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402
import weights  # noqa: E402

st.set_page_config(page_title="Strategic Matrix | HPM Dashboard", page_icon="🧭", layout="wide")
st.title("🧭 Strategic Matrix")
st.caption(
    "Readiness (Supply Score) vs Demand (Demand Opportunity Score) — the charter's proposed enhancement "
    "over a flat ranked list for leadership discussions."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df, is_custom = weights.load_index()
weights.show_banner("matrix")
has_hpm_list = "is_existing_hpm" in df.columns and int(df["is_existing_hpm"].sum()) > 0

with st.sidebar:
    st.header("Quadrant cut-offs")
    mode = st.radio("Split at", ["Median of each axis", "Fixed scores"],
                    help="The median split always puts about half the malls on each side, however low the "
                         "scores are. Fixed scores let you set a real bar.")
    if mode == "Fixed scores":
        supply_cut = st.slider("Supply ≥ (high readiness)", 0, 100, int(round(df["supply_score"].median())))
        demand_cut = st.slider("Demand ≥ (high demand)", 0, 100, int(round(df["demand_score"].median())))
    else:
        supply_cut, demand_cut = float(df["supply_score"].median()), float(df["demand_score"].median())
    label_n = st.slider("Label the top N malls", 0, 30, 10)
    size_by_pop = st.checkbox("Size dots by nearby population", value=True)

df = scoring.add_strategic_quadrant(df, supply_cut=supply_cut, demand_cut=demand_cut)

# Okabe-Ito palette: distinguishable with common forms of colour blindness.
QUADRANT_COLORS = {
    "Pioneer HPM": "#0072B2",
    "Quick Wins": "#009E73",
    "Strategic Investment": "#E69F00",
    "Future Monitoring": "#999999",
}
df["label"] = df["name"].where(df["rank"] <= label_n, "")
df["hpm_status"] = df["is_existing_hpm"].map({1: "Existing HPM", 0: "Not yet an HPM"}) if has_hpm_list else "Mall"
df["nearby_people"] = (df["pop_reach_weighted"] + df["worker_reach_weighted"]).clip(lower=1) \
    if {"pop_reach_weighted", "worker_reach_weighted"} <= set(df.columns) else 1.0

fig = px.scatter(
    df, x="demand_score", y="supply_score", color="quadrant", color_discrete_map=QUADRANT_COLORS,
    size="nearby_people" if size_by_pop else None, size_max=22, text="label", hover_name="name",
    hover_data={"rank": True, "region": True, "operator": True, "hpm_index": ":.1f", "demand_score": ":.1f",
                "supply_score": ":.1f", "label": False, "nearby_people": False, "hpm_status": False},
    labels={"demand_score": "Demand Opportunity Score →", "supply_score": "Supply Readiness Score →",
            "quadrant": "Quadrant", "hpm_status": "", "hpm_index": "HPM Index", "rank": "Rank"},
    category_orders={"quadrant": list(QUADRANT_COLORS)},
)
fig.update_traces(textposition="top center", textfont_size=10)
if has_hpm_list:
    # A ring around each existing HPM, as one legend entry (colour already encodes the quadrant;
    # also encoding HPM status as a symbol multiplied the legend into eight entries).
    hpm = df[df["is_existing_hpm"] == 1]
    fig.add_scatter(x=hpm["demand_score"], y=hpm["supply_score"], mode="markers", name="Existing HPM",
                    hoverinfo="skip", marker=dict(symbol="circle-open", size=17, color="#222222", line=dict(width=2)))

x_max = max(df["demand_score"].max() * 1.08, demand_cut * 1.2, 10)
y_max = max(df["supply_score"].max() * 1.08, supply_cut * 1.2, 10)
shade = {  # (x0, x1, y0, y1, colour, label, label anchor)
    "Pioneer HPM": (demand_cut, x_max, supply_cut, y_max, "#0072B2", "right", "top"),
    "Quick Wins": (0, demand_cut, supply_cut, y_max, "#009E73", "left", "top"),
    "Strategic Investment": (demand_cut, x_max, 0, supply_cut, "#E69F00", "right", "bottom"),
    "Future Monitoring": (0, demand_cut, 0, supply_cut, "#999999", "left", "bottom"),
}
for name, (x0, x1, y0, y1, colour, xa, ya) in shade.items():
    fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=colour, opacity=0.07, line_width=0, layer="below")
    fig.add_annotation(
        x=x1 if xa == "right" else x0, y=y1 if ya == "top" else y0, text=f"<b>{name}</b>", showarrow=False,
        xanchor=xa, yanchor=ya, xshift=-6 if xa == "right" else 6, yshift=-6 if ya == "top" else 6,
        font=dict(color=colour, size=13),
    )
fig.add_vline(x=demand_cut, line_dash="dash", line_color="gray")
fig.add_hline(y=supply_cut, line_dash="dash", line_color="gray")
fig.update_xaxes(range=[0, x_max])
fig.update_yaxes(range=[0, y_max])
fig.update_layout(height=680, legend=dict(orientation="h", yanchor="bottom", y=-0.25))
st.plotly_chart(fig, use_container_width=True)
st.caption(
    f"Split at Demand {demand_cut:.1f} and Supply {supply_cut:.1f} "
    f"({'the median of each axis' if mode.startswith('Median') else 'fixed scores you chose'}). "
    + ("Ringed dots are existing HPMs. " if has_hpm_list else "")
    + ("Dot size is the distance-weighted residents + workers nearby." if size_by_pop else "")
)

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
table = subset[["rank", "name", "region", "operator", "supply_score", "demand_score", "hpm_index"]].rename(
    columns={"rank": "Rank", "name": "Mall", "region": "Region", "operator": "Operator",
             "supply_score": "Supply", "demand_score": "Demand", "hpm_index": "HPM Index"})
st.dataframe(table.style.format({"Supply": "{:.1f}", "Demand": "{:.1f}", "HPM Index": "{:.1f}"}),
             hide_index=True, use_container_width=True)
st.download_button(f"Download {selected_quadrant} (CSV)", table.to_csv(index=False).encode("utf-8"),
                   file_name=f"hpm_{selected_quadrant.lower().replace(' ', '_')}.csv", mime="text/csv")
