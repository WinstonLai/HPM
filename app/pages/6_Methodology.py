"""Page 7 - Methodology: plain-language explanation of the data, scoring
formula, and normalization approach, with a live worked example built from
real numbers so business users can see exactly how any mall's score is
calculated (not just read the formula)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402

st.set_page_config(page_title="Methodology | HPM Dashboard", page_icon="📖", layout="wide")
st.title("📖 Methodology: How the Score Works")
st.caption(
    "A plain-language walkthrough of where the data comes from and how a mall's HPM Index "
    "is actually calculated — with a real, working example below."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

category_scores = data_loader.load_category_scores()
index_df = data_loader.load_default_index()

# --------------------------------------------------------------------------------
st.header("1. The big picture")
st.markdown(
    """
Every mall gets **one score out of 100** — the **HPM Index** — built from two halves:

- **Supply Readiness (70% of the score)** — how much of the health-promoting stuff
  (healthy dining, gyms, clinics, parks, community programmes, an engaged landlord)
  already exists at or near the mall today.
- **Demand Opportunity (30% of the score)** — how much *potential* there is around the
  mall: nearby population, transport access, and how under-served the area currently is.

A mall doesn't need to win on both. A small mall with almost no gyms or clinics nearby
but a huge residential catchment can still score well — that's the point: the index is
meant to surface **opportunity**, not just reward malls that are already the biggest.
"""
)

col1, col2, col3 = st.columns([2, 1, 2])
with col1:
    st.markdown("#### Supply Readiness\n*(6 categories, weighted)*")
with col2:
    st.markdown("<h2 style='text-align:center'>×70% +</h2>", unsafe_allow_html=True)
with col3:
    st.markdown("#### Demand Opportunity\n*(3 factors, weighted)*")

st.divider()

# --------------------------------------------------------------------------------
st.header("2. What each category actually measures")

CATEGORY_INFO = [
    ("A_dining_score", "Supply", "🍽️", "Healthy Dining",
     "Healthier Dining Programme outlets, HPB dining partners, and licensed supermarkets "
     "found at or within ~200m of the mall.",
     "HPB: Healthier Eateries, Healthier Dining Partners · NEA: Supermarket Licences"),
    ("B_fitness_score", "Supply", "🏋️", "Physical Activity",
     "Gyms and sport facilities at or within ~200m of the mall.",
     "HPB: Gyms@SG · SportSG: Sport Facilities"),
    ("C_engagement_score", "Supply", "🤝", "H365 & HPB Engagement",
     "Community Club / PAssion WaVe outlets within ~500m — used as a proxy since "
     "no public dataset of actual H365 event locations exists (see Limitations below).",
     "People's Association: Community Clubs"),
    ("D_healthcare_score", "Supply", "💊", "Healthcare",
     "CHAS clinics and licensed pharmacies at or within ~200m of the mall.",
     "MOH: CHAS Clinics · HSA: Licensed Pharmacies"),
    ("E_infra_score", "Supply", "🌳", "Healthy Infrastructure",
     "Parks and park facilities (playgrounds, fitness corners, green spaces) within ~500m, "
     "plus bicycle parking racks at or within ~200m of the mall.",
     "HPB: Parks@SG · NParks: Park Facilities · LTA: Bicycle Rack"),
    ("F_partnership_score", "Supply", "🏢", "Partnership Readiness",
     "A proxy: the size of the mall operator's portfolio (bigger chains are more likely "
     "to have centralised CSR/health-programme capacity), plus a bonus for the one "
     "HPM partnership HPB's own website confirms (Downtown East).",
     "Wikipedia mall-operator scrape · hpb.gov.sg"),
    ("reach_population_score", "Demand", "👨‍👩‍👧", "Reach & Population",
     "Resident population (and separately, senior population) within ~1.2km of the mall.",
     "SingStat: Census 2020 population by subzone · URA: subzone boundaries"),
    ("accessibility_score", "Demand", "🚌", "Accessibility",
     "MRT exits within ~1.2km and bus stops within ~400m.",
     "LTA: MRT Station Exits, Bus Stops"),
    ("engagement_gap_score", "Demand", "📊", "Engagement Gap",
     "The inverse of the H365 & HPB Engagement score — a mall with high catchment "
     "potential but low existing engagement represents the biggest untapped opportunity.",
     "Derived: 100 − H365 & HPB Engagement score"),
]

supply_tab, demand_tab = st.tabs(["Supply Readiness categories", "Demand Opportunity factors"])
for tab, group in ((supply_tab, "Supply"), (demand_tab, "Demand")):
    with tab:
        for col, grp, icon, label, desc, source in CATEGORY_INFO:
            if grp != group:
                continue
            weight = (
                scoring.DEFAULT_SUPPLY_WEIGHTS.get(col) if group == "Supply"
                else scoring.DEFAULT_DEMAND_WEIGHTS.get(col)
            )
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"**{icon} {label}**  \n{desc}  \n*Source: {source}*")
                c2.metric("Default weight", f"{weight:.0f}%")

st.caption(
    "These default weights come from the charter's own illustrative weights. They aren't "
    "fixed — try changing them yourself on the **What-If Simulator** page and watch every "
    "ranking update instantly."
)

st.divider()

# --------------------------------------------------------------------------------
st.header("3. Why we don't just count amenities")
st.markdown(
    """
A bigger mall will almost always have more of everything — more dining options, more
clinics, more parks nearby — simply because it's bigger, not because it's more
health-promoting. Counting raw numbers would always favour big malls over small,
highly-focused ones. The project charter's own example makes the point:
"""
)

example_col1, example_col2 = st.columns(2)
with example_col1:
    st.markdown("**Raw count ranking**")
    st.dataframe(
        pd.DataFrame({
            "Mall": ["Mall A", "Mall B"],
            "Healthy dining stores": [20, 8],
            "Total F&B stores": [100, 20],
        }),
        hide_index=True, use_container_width=True,
    )
    st.caption("By raw count, Mall A (20) looks better than Mall B (8).")
with example_col2:
    st.markdown("**Normalised ranking**")
    st.dataframe(
        pd.DataFrame({
            "Mall": ["Mall A", "Mall B"],
            "% healthy dining": ["20%", "40%"],
        }),
        hide_index=True, use_container_width=True,
    )
    st.caption("But as a *share* of what's on offer, Mall B is actually twice as health-focused.")

st.markdown(
    """
**Our approach:** we don't have a public directory of every mall's *total* tenant count
(the figure the charter's example divides by), so instead each raw count is
**min-max scaled to 0–100 across all 185 malls**:

> `score = (mall's count − lowest count in Singapore) / (highest count in Singapore − lowest count) × 100`

A mall with the fewest amenities in its category scores 0; the mall with the most scores
100; everyone else falls proportionally in between. This doesn't reproduce the charter's
exact tenant-percentage formula, but it fixes the same underlying problem — a big mall's
raw count no longer automatically wins.
"""
)

with st.expander("See this normalisation on real data — Healthy Dining"):
    lo, hi = category_scores["A_dining_count"].min(), category_scores["A_dining_count"].max()
    st.markdown(
        f"Across all {len(category_scores)} malls, the Healthy Dining outlet count ranges "
        f"from **{lo}** to **{hi}**. So a mall with **{int((lo+hi)/2)}** outlets would score "
        f"roughly **{(( (lo+hi)/2 - lo) / (hi - lo) * 100):.0f}/100** on this category — "
        f"regardless of whether it's a huge or tiny mall."
    )

st.divider()

# --------------------------------------------------------------------------------
st.header("4. Try it yourself: how one mall's score is built")
st.markdown("Pick any mall below to see its actual numbers plugged into the formula.")

mall_options = sorted(index_df["name"])
top_mall_name = index_df.sort_values("hpm_index", ascending=False)["name"].iloc[0]
default_idx = mall_options.index(top_mall_name)
mall_name = st.selectbox("Mall", mall_options, index=default_idx)
row = index_df[index_df["name"] == mall_name].iloc[0]

supply_rows = []
supply_total_weight = sum(scoring.DEFAULT_SUPPLY_WEIGHTS.values())
for col, w in scoring.DEFAULT_SUPPLY_WEIGHTS.items():
    supply_rows.append({
        "Category": scoring.CATEGORY_LABELS[col],
        "Score (0-100)": round(row[col], 1),
        "Weight": f"{w / supply_total_weight * 100:.1f}%",
        "Contribution": round(row[col] * w / supply_total_weight, 2),
    })
supply_table = pd.DataFrame(supply_rows)

demand_rows = []
demand_total_weight = sum(scoring.DEFAULT_DEMAND_WEIGHTS.values())
for col, w in scoring.DEFAULT_DEMAND_WEIGHTS.items():
    demand_rows.append({
        "Category": scoring.CATEGORY_LABELS[col],
        "Score (0-100)": round(row[col], 1),
        "Weight": f"{w / demand_total_weight * 100:.1f}%",
        "Contribution": round(row[col] * w / demand_total_weight, 2),
    })
demand_table = pd.DataFrame(demand_rows)

wcol1, wcol2 = st.columns(2)
with wcol1:
    st.markdown("**Step A — Supply Readiness**")
    st.dataframe(supply_table, hide_index=True, use_container_width=True)
    st.markdown(f"Sum of contributions = **Supply Score = {row['supply_score']:.1f}**")
with wcol2:
    st.markdown("**Step B — Demand Opportunity**")
    st.dataframe(demand_table, hide_index=True, use_container_width=True)
    st.markdown(f"Sum of contributions = **Demand Score = {row['demand_score']:.1f}**")

st.markdown("**Step C — Combine them (70% Supply + 30% Demand)**")
st.latex(
    r"\text{HPM Index} = " + f"{row['supply_score']:.1f}" + r"\times 0.70 + "
    + f"{row['demand_score']:.1f}" + r"\times 0.30 = " + f"{row['hpm_index']:.1f}"
)
st.success(
    f"**{mall_name}**'s HPM Index is **{row['hpm_index']:.1f} / 100** — "
    f"rank **#{int(row['rank'])}** of {len(index_df)}, **{row['tier']}** tier, in the "
    f"**{row['quadrant']}** quadrant of the Strategic Matrix."
)

fig = px.bar(
    pd.concat([
        supply_table.assign(Block="Supply Readiness"),
        demand_table.assign(Block="Demand Opportunity"),
    ]),
    x="Contribution", y="Category", color="Block", orientation="h",
    labels={"Contribution": "Points contributed to that block's score"},
)
fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, use_container_width=True)

st.caption(
    "This is the exact same calculation the What-If Simulator runs live when you move a "
    "weight slider — only the weights change, not the underlying category scores."
)

st.divider()

# --------------------------------------------------------------------------------
st.header("5. What this score doesn't capture")
st.markdown(
    """
Being transparent about the gaps matters as much as explaining what works. Two categories
are **proxies**, not the literal metric named in the charter, because no public dataset
for the real thing exists yet:

- **H365 & HPB Engagement** — there's no public dataset of actual H365 event locations or
  attendance, so we use nearby Community Club density as a stand-in for "community
  activation" in the area.
- **Partnership Readiness** — there's no public record of which malls have an existing HPB
  partnership (HPB's own website names only one: Downtown East), so we use the mall
  operator's portfolio size as a rough proxy for how likely they are to have the capacity
  to partner.

A few other simplifications:

- **Healthy Dining is a density score, not a true "% of F&B outlets" figure** — that needs
  a full per-mall tenant directory, which isn't publicly available.
- **Supermarket presence counts any licensed supermarket**, not specifically ones "with
  healthier choice options" as the charter names it — no public dataset flags which
  supermarkets carry HPB's healthier-choice range at the outlet level.
- **Population catchment uses an approximate centroid** for each URA subzone (not the exact
  boundary), so it can occasionally under- or over-count a mall sitting right at a
  subzone's edge.
- **Mall operator names are free text** scraped from Wikipedia infoboxes, so near-identical
  entities (e.g. two slightly different names for the same landlord) aren't always merged.

Full source citations and dataset IDs are in the project's `README.md`.
"""
)
