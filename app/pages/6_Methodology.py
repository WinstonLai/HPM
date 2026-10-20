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

supply_pct = round(scoring.SUPPLY_BLOCK_WEIGHT)
demand_pct = round(scoring.DEMAND_BLOCK_WEIGHT)
n_malls = len(index_df)
n_known_operator = int((index_df["operator"] != "Unknown").sum())

# --------------------------------------------------------------------------------
st.header("1. The big picture")
st.markdown(
    f"""
Every mall gets **one score on a 0–100 scale** — the **HPM Index** — built from two halves:

- **Supply Readiness ({supply_pct}% of the score)** — how much of the health-promoting stuff
  (healthy dining, gyms, clinics, parks, community clubs, a partnership-ready landlord)
  already exists at or near the mall today.
- **Demand Opportunity ({demand_pct}% of the score)** — how much *potential* there is around the
  mall: nearby residents, transport access, and how few health-promoting amenities
  the area has per resident ("untapped demand").

Supply carries more than twice the weight of Demand, so a large catchment can lift a mall
but cannot rescue one that has almost nothing on the supply side. The Demand half is
there to separate malls of similar readiness by **opportunity**, and the
**Strategic Matrix** page shows high-demand / low-readiness malls separately so they
aren't lost in the ranking.

**Read the score as a relative ranking, not an absolute "% ready".** Each category is
scaled against the best and worst mall in this list of {n_malls} (Section 3), so even the
top mall is far from 100: the highest HPM Index here is **{index_df['hpm_index'].max():.1f}**
and the average is **{index_df['hpm_index'].mean():.1f}**.

**Where the mall list comes from.** The {n_malls} malls are a union of three Wikipedia
sources (the *List of shopping malls in Singapore*, every article in *Category: Shopping
malls in Singapore*, and the "Housing estate commercial areas" section of *List of commercial
sites in Singapore*), de-duplicated and then geocoded with the OneMap Search API (the top
search hit is used for each name). Candidates that OneMap couldn't geocode were dropped, so
the list is **not guaranteed to be exhaustive**. Each mall's region is the URA region of its
nearest Master Plan subzone centroid.
"""
)

col1, col2, col3 = st.columns([2, 1, 2])
with col1:
    st.markdown(f"#### Supply Readiness ×{supply_pct}%\n*(6 categories, weighted)*")
with col2:
    st.markdown("<h2 style='text-align:center'>+</h2>", unsafe_allow_html=True)
with col3:
    st.markdown(f"#### Demand Opportunity ×{demand_pct}%\n*(3 factors, weighted)*")

st.divider()

# --------------------------------------------------------------------------------
st.header("2. What each category actually measures")

CATEGORY_INFO = [
    ("A_dining_score", "Supply", "🍽️", "Healthy Dining",
     "A count of three things: (1) HPB Healthier Dining Programme eateries within ~200m of the "
     "mall (or sharing its building name); (2) HPB Healthier Dining Partner outlets whose "
     "listed address contains the mall's name — leaving out any outlet already counted in (1) "
     "(matched on postal code + brand) and repeated rows; (3) NEA-licensed supermarkets whose "
     "listed address contains the mall's name. Any licensed supermarket counts — the data can't "
     "tell us which ones stock healthier-choice ranges.",
     "HPB: Healthier Eateries, Healthier Dining Partners · NEA: Supermarket Licences"),
    ("B_fitness_score", "Supply", "🏋️", "Physical Activity",
     "Gyms@SG gyms plus SportSG sport centres/stadiums/swimming complexes within ~200m "
     "of the mall. Fitness studios and activity-oriented tenants (e.g. sports retailers) "
     "are not in any public dataset and aren't counted.",
     "HPB: Gyms@SG · SportSG: Sport Facilities"),
    ("C_engagement_score", "Supply", "🤝", "H365 & HPB Engagement",
     "A proxy: the number of People's Association Community Clubs / PAssion WaVe outlets "
     "within ~500m. No public dataset of actual H365 event locations exists (see Section 5).",
     "People's Association: Community Clubs"),
    ("D_healthcare_score", "Supply", "💊", "Healthcare",
     "A count of MOH-listed CHAS clinics within ~200m of the mall (or sharing its building "
     "name), plus HSA-licensed pharmacies whose listed address contains the mall's name.",
     "MOH: CHAS Clinics · HSA: Licensed Pharmacies"),
    ("E_infra_score", "Supply", "🌳", "Healthy Infrastructure",
     "A count of HPB Parks@SG parks, plus NParks **playgrounds and fitness areas only**, within "
     "~500m, plus bicycle-rack locations within ~200m. (NParks' file also lists carparks, "
     "noticeboards, toilets, etc.; those are excluded.) Water refill points, quiet corners and "
     "walkability — also in the charter — have no usable data and aren't counted.",
     "HPB: Parks@SG · NParks: Park Facilities · LTA: Bicycle Rack"),
    ("F_partnership_score", "Supply", "🏢", "Partnership Readiness",
     "A proxy, not a record of partnerships: the number of malls in this list that share the "
     "mall's landlord group (scaled 0–100, then × 0.8), plus a flat +20 for any mall flagged as a "
     "confirmed HPB partner (currently only Downtown East, the one HPM partnership named on HPB's "
     "website). Malls with an unknown operator get 0 from the first part (see Section 5). "
     "Landlord and partnership facts can be supplied in data/manual/operators.csv.",
     "Wikipedia infobox (owner › management › developer) · hpb.gov.sg · data/manual/operators.csv"),
    ("reach_population_score", "Demand", "👨‍👩‍👧", "Reach & Population",
     "70% total + 30% senior (65+) *resident* population (Census 2020) of the URA subzones "
     "whose centroid lies within ~1.2km of the mall. Each of the two measures is scaled "
     "0–100 separately, then combined 70/30. Whole-subzone totals are used — they are not "
     "pro-rated by area.",
     "SingStat: Census 2020 resident population by subzone · URA: subzone boundaries"),
    ("accessibility_score", "Demand", "🚌", "Accessibility",
     "50% MRT station exits within ~1.2km + 50% bus stops within ~400m. Each count is scaled "
     "0–100 separately, then averaged.",
     "LTA: MRT Station Exits, Bus Stops"),
    ("engagement_gap_score", "Demand", "📊", "Engagement Gap",
     "The charter's \"untapped demand\" (low healthy-dining exposure, under-served locations), "
     "measured as how **few** health-promoting amenities a catchment has *for its population*: "
     "healthier eateries, gyms/sport facilities and CHAS clinics within ~1.2km. We first work out "
     "how many amenities a catchment of a given size typically has (a fitted trend across all "
     "malls), then rank every mall by how far it falls **short of** that — the biggest shortfall "
     "scores 100, the biggest surplus 0. This is deliberately *not* a plain amenities-per-resident "
     "ratio, which is mostly just population again and would double-count Reach & Population. A "
     "mall with no residents in its catchment has no meaningful gap: it shows as n/a and its "
     "Demand score is worked out from its other factors. Community Clubs are deliberately not "
     "part of it, so it doesn't mirror the H365 & HPB Engagement score.",
     "HPB: Healthier Eateries, Gyms@SG · SportSG · MOH: CHAS Clinics · SingStat: Census 2020"),
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

charter_w = ", ".join(
    f"{scoring.CATEGORY_LABELS[k]} {v}" for k, v in scoring.CHARTER_SUPPLY_WEIGHTS.items()
)
st.caption(
    "Weights shown are each factor's share **within its own block** (they sum to 100% per tab). "
    f"The charter's illustrative Supply weights are {charter_w} — which sum to 90, because the "
    "charter's seventh category, Demand Potential, was 10. Two of them are **proxies** (H365 & HPB "
    "Engagement and Partnership Readiness: see Section 5), so they start lower than the charter's "
    "figures (10 and 5 instead of 15 and 10). All six are then re-scaled to sum to 100 inside the "
    "Supply block, which is why the percentages above are not the raw numbers. The charter does "
    "not specify weights inside Demand, so its three factors are weighted equally. None of "
    "this is fixed — change any of it on the **What-If Simulator** page, which can also switch the "
    "two proxy categories off."
)

st.divider()

# --------------------------------------------------------------------------------
st.header("3. Raw counts vs. normalised scores")
st.markdown(
    """
A bigger mall will almost always have more of everything — more dining options, more
clinics, more parks nearby — simply because it's bigger, not because it's more
health-promoting. Counting raw numbers would always favour big malls over small,
highly-focused ones. The project charter's own example makes the point, and its intended
design is to score each category as a **share** of a mall's tenants:
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
    f"""
**What we actually do:** we don't have a public directory of every mall's *total* tenant
count (the figure the charter's example divides by), so we **cannot** compute the charter's
"% of outlets" metric. Instead each category's raw amenity count is **min-max scaled to
0–100 across all {n_malls} malls**:

> `score = (mall's count − lowest count in the list) / (highest count in the list − lowest count) × 100`

The mall with the fewest in a category scores 0, the mall with the most scores 100, and
everyone else falls proportionally in between.

**What this does and doesn't fix.** Min-max scaling puts nine very different measures
(outlet counts, residents, bus stops…) onto one comparable 0–100 scale so they can be
weighted and added. It is a *linear* rescale of the raw count, so **within a category the
mall ranking is identical to the raw-count ranking — it does not remove the "bigger malls
have more of everything" bias** that the charter warns about. Two further effects follow:

- A single outlier compresses everyone else (e.g. the Healthy Infrastructure count has a median
  of {int(category_scores['E_infra_count'].median())} but a maximum of
  {int(category_scores['E_infra_count'].max())}, so the typical mall scores only
  {category_scores['E_infra_score'].median():.0f}/100 on it).
- The Engagement Gap factor is the one exception: it is scaled by rank, not min-max
  (see Section 2).
- Scores are relative to this list — adding or removing malls changes every score.
"""
)

with st.expander("See this scaling on real data — Healthy Dining"):
    lo, hi = category_scores["A_dining_count"].min(), category_scores["A_dining_count"].max()
    example_count = int(round((lo + hi) / 2))
    st.markdown(
        f"Across all {len(category_scores)} malls, the Healthy Dining count ranges "
        f"from **{lo}** to **{hi}**. So a mall with **{example_count}** would score "
        f"**{(example_count - lo) / (hi - lo) * 100:.0f}/100** on this category."
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

def contribution_table(weights: dict) -> pd.DataFrame:
    """One row per factor. A factor that is n/a for this mall (NaN) is left out
    and the remaining weights are re-scaled to 100%, exactly as the index does."""
    available = sum(w for col, w in weights.items() if pd.notna(row[col]))
    rows = []
    for col, w in weights.items():
        if pd.isna(row[col]):
            rows.append({"Category": scoring.CATEGORY_LABELS[col], "Score (0-100)": "n/a",
                         "Weight (within block)": "0.0%", "Contribution": 0.0})
            continue
        rows.append({
            "Category": scoring.CATEGORY_LABELS[col],
            "Score (0-100)": f"{row[col]:.1f}",  # text, like the "n/a" rows, so Arrow sees one type
            "Weight (within block)": f"{w / available * 100:.1f}%",
            "Contribution": round(row[col] * w / available, 2),
        })
    return pd.DataFrame(rows)


supply_table = contribution_table(scoring.DEFAULT_SUPPLY_WEIGHTS)
demand_table = contribution_table(scoring.DEFAULT_DEMAND_WEIGHTS)

wcol1, wcol2 = st.columns(2)
with wcol1:
    st.markdown("**Step A — Supply Readiness**")
    st.dataframe(supply_table, hide_index=True, use_container_width=True)
    st.markdown(f"Sum of contributions = **Supply Score = {row['supply_score']:.1f}**")
with wcol2:
    st.markdown("**Step B — Demand Opportunity**")
    st.dataframe(demand_table, hide_index=True, use_container_width=True)
    st.markdown(f"Sum of contributions = **Demand Score = {row['demand_score']:.1f}**")

st.markdown(f"**Step C — Combine them ({supply_pct}% Supply + {demand_pct}% Demand)**")
st.latex(
    r"\text{HPM Index} = " + f"{row['supply_score']:.1f}"
    + rf"\times {scoring.SUPPLY_BLOCK_WEIGHT / 100:.2f} + "
    + f"{row['demand_score']:.1f}"
    + rf"\times {scoring.DEMAND_BLOCK_WEIGHT / 100:.2f} = " + f"{row['hpm_index']:.1f}"
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
st.header("5. Tiers, quadrants and what this score doesn't capture")

st.subheader("How tiers and quadrants are assigned")
st.markdown(
    """
Both are **relative** labels, not pass/fail thresholds:

- **Tier** — malls are sorted by HPM Index and split into four groups of roughly equal size:
  the top quarter are **Platinum**, then **Gold**, **Silver**, and the bottom quarter
  **Bronze**. A Platinum mall is simply in the top ~25% of this list, not "certified ready".
- **Strategic Matrix quadrant** — a mall is "high" on Supply (or Demand) if its Supply
  (or Demand) score is at or above the **median** of all malls. High Supply + High Demand =
  *Pioneer HPM*; High Supply + Low Demand = *Quick Wins*; Low Supply + High Demand =
  *Strategic Investment*; Low + Low = *Future Monitoring*. Because the split is at the
  median, about half of all malls are always "high" on each axis, however low the scores are.
- Top 10 / 20 / 50 shortlists are simply the best-ranked 10 / 20 / 50 malls.
"""
)

gap_vs_reach_corr = category_scores["engagement_gap_score"].corr(category_scores["reach_population_score"])
n_gap_na = int(category_scores["engagement_gap_score"].isna().sum())

st.subheader("Proxies instead of the charter's real metrics")
st.markdown(
    f"""
Two categories are **proxies**, not the metric named in the charter, because no public
dataset for the real thing exists:

- **H365 & HPB Engagement** — there's no public dataset of H365 event locations or attendance,
  so we count nearby Community Clubs / PAssion WaVe outlets (no mall here has more than
  {int(category_scores['C_engagement_count'].max())} within 500m, so in practice it is a coarse 0 / 50 / 100 score). It measures *proximity to a CC*, not
  health-programme activity.
- **Partnership Readiness** — there's no public record of which malls have an HPB
  partnership (HPB's website names only Downtown East), so we use the number of malls in
  *this list* that share the mall's landlord group (operator names are merged via
  `data/manual/operator_aliases.csv`, so e.g. all the CapitaLand trust names count as one).
  **A landlord could be found on Wikipedia for only {n_known_operator} of {n_malls} malls**; the
  rest are "Unknown" and score 0, so this category is effectively 0 for
  {(category_scores['F_partnership_score'] == 0).sum()} of {n_malls} malls and does very little to
  separate them. Fill in `data/manual/operators.csv` with authoritative landlord and
  partnership facts to improve it.

Because both are weak, they start with **lower default weights** than the charter's
illustrative ones, and the What-If Simulator has a switch to drop them from the index entirely.

**Engagement Gap and Reach & Population.** Engagement Gap is measured against the amenities a
catchment of that population would typically have, so it adds information beyond Reach & Population
rather than repeating it: the two are correlated at only **{gap_vs_reach_corr:.2f}**. (A plain
amenities-per-resident ratio would have been strongly tied to population, so population would
have counted twice in the Demand block.) {n_gap_na} mall(s) with no residents in their
catchment have no meaningful gap; their Demand score is computed from the other factors.
"""
)

st.subheader("Data coverage: how many malls score zero")
raw_cols = {
    "Healthy Dining": "A_dining_count",
    "Physical Activity": "B_fitness_count",
    "H365 & HPB Engagement": "C_engagement_count",
    "Healthcare": "D_healthcare_count",
    "Healthy Infrastructure": "E_infra_count",
    "Population catchment": "pop_catchment",
    "MRT exits": "mrt_count",
}
coverage = [
    {"Category": label, "Malls with a count of 0": int((category_scores[col] == 0).sum()),
     "% of malls": f"{(category_scores[col] == 0).mean() * 100:.0f}%"}
    for label, col in raw_cols.items()
]
coverage.append({
    "Category": "Partnership Readiness",
    "Malls with a count of 0": int((category_scores["F_partnership_score"] == 0).sum()),
    "% of malls": f"{(category_scores['F_partnership_score'] == 0).mean() * 100:.0f}%",
})
st.dataframe(pd.DataFrame(coverage), hide_index=True, use_container_width=True)
st.caption(
    "A zero means no matching record was found — either the mall genuinely has none, or the "
    "match failed (see below). A missing count is treated as zero; a factor that is not applicable "
    "(Engagement Gap for a mall with no residents nearby) is skipped and the rest re-weighted."
)

st.subheader("Other simplifications to keep in mind")
st.markdown(
    """
- **Healthy Dining is a density score, not a true "% of F&B outlets" figure** — that needs
  a full per-mall tenant directory, which isn't publicly available. The Healthier Eateries and
  Healthier Dining Partners datasets describe many of the same outlets; we remove partner
  outlets that match an eatery on postal code + brand, but a duplicate with a differently
  spelled brand or no postal code in its address can still be counted twice.
- **Supermarket presence counts any licensed supermarket**, not specifically ones "with
  healthier choice options" as the charter names it.
- **Catchments are straight-line circles, not mall footprints.** Counts within 200m / 500m
  (and 1.2km / 400m for demand) include amenities that belong to neighbouring buildings, so
  malls in dense clusters (e.g. Orchard) share and double-count the same amenities.
- **Address-text matching depends on naming.** Healthier Dining Partners, pharmacies and
  supermarkets have no coordinates; they only count if the mall's name appears in the
  outlet's address (matched as a whole phrase). Outlets listed by street address alone are
  missed, so those categories are more likely to under-count.
- **Population is residents only, from Census 2020.** Worker, visitor and non-resident
  populations (which the charter lists) are not included. Subzones are placed by an
  approximate centroid (a simple average of boundary points, not the exact boundary), and a
  subzone's whole population is counted if its centroid is within 1.2km, otherwise none of
  it is — so a mall at the edge of a large subzone can be under- or over-counted.
- **Several charter measures aren't scored at all** because no public data exists:
  fitness studios and activity-oriented tenants, water refill points, quiet corners,
  walkability, Healthier SG providers, event history, and landlord willingness.
- **Geocoding is validated, not manual.** OneMap's first hit is often the wrong building, so each
  mall is only placed on a OneMap result whose building name matches the mall's name; malls with no
  such result are dropped (listed in `data/processed/registry_qa.csv`) unless a fix is supplied in
  `data/manual/geocode_overrides.csv`. A matching name is still not proof the point is right.
- **Mall operator names are free text** from Wikipedia infoboxes (owner, else management, else
  developer). Known variants of one landlord are merged by hand in `data/manual/operator_aliases.csv`,
  but new variants will not be merged automatically.

Full source citations and dataset IDs are in the project's `README.md`.
"""
)
