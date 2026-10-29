"""Methodology: plain-language explanation of the data, scoring
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
from safe_text import escape_md  # noqa: E402

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


@st.cache_data
def _scenario_table(scores: pd.DataFrame) -> pd.DataFrame:
    return scoring.scenario_comparison(scores)


@st.cache_data
def _stability_table(scores: pd.DataFrame) -> pd.DataFrame:
    return scoring.rank_stability(scores)


supply_pct = round(scoring.SUPPLY_BLOCK_WEIGHT)
demand_pct = round(scoring.DEMAND_BLOCK_WEIGHT)
n_malls = len(index_df)
n_known_operator = int((index_df["operator"] != "Unknown").sum())

st.markdown(
    "**Contents:** [1. The big picture](#big-picture) · [2. What each category measures](#categories) · "
    "[3. Raw counts vs. normalised scores](#normalisation) · [4. Worked example](#worked-example) · "
    "[5. Tiers and limitations](#limitations) · [6. How robust is the ranking?](#robustness)"
)

# --------------------------------------------------------------------------------
st.header("1. The big picture", anchor="big-picture")
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
sites in Singapore*), de-duplicated and then geocoded with the OneMap Search API (a hit is accepted only if its
building name matches the mall's name; the top hit alone is often the wrong building). Candidates
with no matching hit were dropped, so
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
st.header("2. What each category actually measures", anchor="categories")

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
     "Gyms@SG gyms, SportSG sport centres/stadiums/swimming complexes, and commercial gyms and "
     "fitness studios from OpenStreetMap (OSM venues that duplicate a listed one are dropped), "
     "within ~200m of the mall. OSM coverage of small studios is patchy, and sports retailers "
     "and other activity-oriented tenants are not counted.",
     "HPB: Gyms@SG · SportSG: Sport Facilities · OpenStreetMap contributors"),
    ("C_engagement_score", "Supply", "🤝", "H365 & HPB Engagement",
     "A proxy: the number of People's Association Community Clubs / PAssion WaVe outlets "
     "within ~500m. No public dataset of actual H365 event locations exists (see Section 5).",
     "People's Association: Community Clubs"),
    ("D_healthcare_score", "Supply", "💊", "Healthcare",
     "A count of MOH-listed CHAS clinics within ~200m of the mall (or sharing its building "
     "name), plus HSA-licensed pharmacies whose listed address contains the mall's name.",
     "MOH: CHAS Clinics · HSA: Licensed Pharmacies"),
    ("E_infra_score", "Supply", "🌳", "Healthy Infrastructure",
     "A count of HPB Parks@SG parks, plus NParks **playgrounds, fitness areas, drinking fountains "
     "(water refill points) and foot-relax stations only**, within ~500m, plus bicycle-rack "
     "locations within ~200m. (NParks' file also lists carparks, noticeboards, toilets, etc.; "
     "those are excluded.) These are park facilities near the mall, not facilities inside it. "
     "Quiet corners and walkability — also in the charter — have no usable data and aren't counted.",
     "HPB: Parks@SG · NParks: Park Facilities · LTA: Bicycle Rack"),
    ("F_partnership_score", "Supply", "🏢", "Partnership Readiness",
     "A proxy, not a record of partnerships: the number of malls in this list that share the "
     "mall's landlord group (scaled 0–100, then × 0.8), plus a flat +20 for any mall flagged as a "
     "confirmed HPB partner (currently only Downtown East, the one HPM partnership named on HPB's "
     "website). Malls with an unknown operator get 0 from the first part (see Section 5). "
     "Landlord and partnership facts can be supplied in data/manual/operators.csv.",
     "Wikipedia infobox (owner › management › developer) · hpb.gov.sg · data/manual/operators.csv"),
    ("reach_population_score", "Demand", "👨‍👩‍👧", "Reach & Population",
     "50% residents + 30% seniors (65+) + 20% workers, each scaled 0–100 separately. People are "
     "counted by **distance**: a subzone's people count fully at the mall and fade linearly to "
     "nothing at 2km (measured to the subzone's centroid), so a subzone just across a line no "
     "longer vanishes. Workers are employed residents by planning area of *workplace* (Census "
     "2020), spread over that area's subzones by land area — so this is a coarse daytime signal "
     "that misses foreign workers and visitors.",
     "SingStat: Census 2020 residents by subzone, employed residents by workplace area · URA: subzone boundaries"),
    ("accessibility_score", "Demand", "🚌", "Accessibility",
     "50% MRT + 50% bus. MRT counts each **station** once (the LTA file has one row per exit, so "
     "an interchange used to look like many stations) and weights nearer stations more: a station "
     "adds 1 at the mall, fading to 0 at 1.2km. Bus stops fade to 0 at 400m. Each is scaled "
     "0–100 separately, then averaged. Bus stops are counted, not bus services.",
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
st.header("3. Raw counts vs. normalised scores", anchor="normalisation")
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
        hide_index=True, width="stretch",
    )
    st.caption("By raw count, Mall A (20) looks better than Mall B (8).")
with example_col2:
    st.markdown("**Normalised ranking**")
    st.dataframe(
        pd.DataFrame({
            "Mall": ["Mall A", "Mall B"],
            "% healthy dining": ["20%", "40%"],
        }),
        hide_index=True, width="stretch",
    )
    st.caption("But as a *share* of what's on offer, Mall B is actually twice as health-focused.")

st.markdown(
    f"""
**What we actually do:** we don't have a public directory of every mall's *total* tenant
count (the figure the charter's example divides by), so we **cannot** compute the charter's
"% of outlets" metric. Instead each category's raw amenity count is **min-max scaled to
0–100 across all {n_malls} malls**, after capping at the 95th percentile:

> `score = (min(count, cap) − lowest count) / (cap − lowest count) × 100`, where `cap` is the 95th-percentile count

The mall with the fewest in a category scores 0; the mall at or above the cap (roughly the top 5%)
scores 100, and everyone else falls proportionally in between. The cap stops one very large
mall from squashing everyone else's score.

**What this does and doesn't fix.** Min-max scaling puts nine very different measures
(outlet counts, residents, bus stops…) onto one comparable 0–100 scale so they can be
weighted and added. It is a *linear* rescale of the raw count, so **within a category the
mall ranking is identical to the raw-count ranking — it does not remove the "bigger malls
have more of everything" bias** that the charter warns about. Two further effects follow:

- Counts are capped at the 95th percentile, so the top ~5% of malls tie at 100 in each category
  (e.g. Healthy Infrastructure ranges up to {int(category_scores['E_infra_count'].max())}, but the
  cap is {category_scores['E_infra_count'].quantile(0.95):.0f}). Without the cap a single outlier
  dragged everyone else down, and the categories' *effective* influence drifted far from their
  nominal weights (see Section 6).
- The Engagement Gap factor is the one exception: it is scaled by rank, not min-max
  (see Section 2).
- Scores are relative to this list — adding or removing malls changes every score.
"""
)

with st.expander("See this scaling on real data — Healthy Dining"):
    lo = category_scores["A_dining_count"].min()
    hi = category_scores["A_dining_count"].max()
    cap = category_scores["A_dining_count"].quantile(0.95)
    example_count = int(round((lo + cap) / 2))
    st.markdown(
        f"Across all {len(category_scores)} malls, the Healthy Dining count ranges "
        f"from **{lo}** to **{hi}**, and the 95th-percentile cap is **{cap:.0f}**. So a mall with "
        f"**{example_count}** would score **{(example_count - lo) / (cap - lo) * 100:.0f}/100** on "
        f"this category, and any mall with {cap:.0f} or more scores 100."
    )

st.divider()

# --------------------------------------------------------------------------------
st.header("4. Try it yourself: how one mall's score is built", anchor="worked-example")
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
    st.dataframe(supply_table, hide_index=True, width="stretch")
    st.markdown(f"Sum of contributions = **Supply Score = {row['supply_score']:.1f}**")
with wcol2:
    st.markdown("**Step B — Demand Opportunity**")
    st.dataframe(demand_table, hide_index=True, width="stretch")
    st.markdown(f"Sum of contributions = **Demand Score = {row['demand_score']:.1f}**")

st.markdown(f"**Step C — Combine them ({supply_pct}% Supply + {demand_pct}% Demand)**")
st.latex(
    r"\text{HPM Index} = " + f"{row['supply_score']:.1f}"
    + rf"\times {scoring.SUPPLY_BLOCK_WEIGHT / 100:.2f} + "
    + f"{row['demand_score']:.1f}"
    + rf"\times {scoring.DEMAND_BLOCK_WEIGHT / 100:.2f} = " + f"{row['hpm_index']:.1f}"
)
st.success(
    f"**{escape_md(mall_name)}**'s HPM Index is **{row['hpm_index']:.1f} / 100** — "
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
st.plotly_chart(fig, width="stretch")

st.caption(
    "This is the exact same calculation the What-If Simulator runs live when you move a "
    "weight slider — only the weights change, not the underlying category scores."
)

st.divider()

# --------------------------------------------------------------------------------
st.header("5. Tiers, quadrants and what this score doesn't capture", anchor="limitations")

st.subheader("How tiers and quadrants are assigned")
t = scoring.TIER_THRESHOLDS
st.markdown(
    f"""
Both are labels within this list of malls, not pass/fail certifications:

- **Tier** — fixed cut-offs on the HPM Index: **Platinum** ≥ {t['Platinum']:.0f}, **Gold** ≥ {t['Gold']:.0f},
  **Silver** ≥ {t['Silver']:.0f}, otherwise **Bronze**. Because the cut-offs are fixed (earlier versions
  split the list into four equal quarters), the number of malls in each tier changes when the weights or the
  mall list change. The index is itself relative — every category is scaled against the best malls in this
  list — so a Platinum mall is "high within this list", not "certified ready". The cut-offs are a judgement
  call; move them on the What-If Simulator.
- **Strategic Matrix quadrant** — a mall is "high" on Supply (or Demand) if its Supply
  (or Demand) score is at or above the cut-off, which by default is the **median** of all malls.
  High Supply + High Demand = *Pioneer HPM*; High Supply + Low Demand = *Quick Wins*;
  Low Supply + High Demand = *Strategic Investment*; Low + Low = *Future Monitoring*. A median split
  always puts about half of all malls on each side however low the scores are, so the Strategic Matrix
  page can switch to fixed cut-offs instead.
- Top 10 / 20 / 50 shortlists are simply the best-ranked 10 / 20 / 50 malls.
- Your weights and cut-offs from the What-If Simulator carry over to the other pages. This page always
  explains the *default* scoring.
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
    "MRT stations within 1.2km": "mrt_count",
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
st.dataframe(pd.DataFrame(coverage), hide_index=True, width="stretch")
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
  (and 1.2km / 400m for demand) include amenities that belong to neighbouring buildings. To stop
  malls in dense clusters (e.g. Orchard, Bugis) each claiming the same eatery, gym, clinic or bike
  rack, those on-site amenities count for their *nearest* mall only. Parks and community clubs
  (500m) and the demand-side catchments are still shared, because they genuinely serve several malls.
- **Address-text matching depends on naming.** Healthier Dining Partners, pharmacies and
  supermarkets have no coordinates; they only count if the mall's name appears in the
  outlet's address (matched as a whole phrase). Outlets listed by street address alone are
  missed, so those categories are more likely to under-count.
- **Population is mostly residents, from Census 2020.** Workers are included but only as employed
  *residents*, published per planning area and spread over its subzones by land area; foreign
  workers, tourists and other visitors (which the charter also lists) are not. Subzones are placed
  by an approximate centroid (a simple average of boundary points, not the exact boundary), so a
  mall beside a very large subzone can still be under- or over-counted. The Engagement Gap keeps
  a hard 1.2km circle of residents, to match the circle its amenity counts use.
- **Several charter measures aren't scored** because no usable data exists: quiet corners and
  calm rooms, walkability, Healthier SG providers, event history, and landlord willingness.
  Fitness studios and water refill points are only partly covered (OpenStreetMap venues; park
  drinking fountains).
- **Geocoding is validated, not manual.** OneMap's first hit is often the wrong building, so each
  mall is only placed on a OneMap result whose building name matches the mall's name; malls with no
  such result are dropped (listed in `data/processed/registry_qa.csv`) unless a fix is supplied in
  `data/manual/geocode_overrides.csv`. A matching name is still not proof the point is right.
- **The mall list is incomplete.** It comes from Wikipedia, which missed 14 of the 48 malls HPB
  already designates as HPMs (they were added from HPB's list). Other malls, especially newer
  or suburban ones, are probably missing too, and malls added from HPB's list have no landlord
  recorded.
- **Mall operator names are free text** from Wikipedia infoboxes (owner, else management, else
  developer). Known variants of one landlord are merged by hand in `data/manual/operator_aliases.csv`,
  but new variants will not be merged automatically.

Full source citations and dataset IDs are in the project's `README.md`.
"""
)

st.divider()

# --------------------------------------------------------------------------------
st.header("6. How robust is the ranking?", anchor="robustness")
st.markdown(
    """
Every ranking here rests on weights that are judgement calls, so it is worth knowing how much they
matter. Two checks follow. Neither changes the defaults; they show how much of the shortlist survives
other reasonable choices.
"""
)

st.subheader("Other readings of the charter's weights")
st.dataframe(_scenario_table(category_scores), hide_index=True, width="stretch")
st.caption(
    "The charter is ambiguous: its category weights (25/20/15/10/10/10 plus Demand Potential 10) sum to "
    "100 with Supply at 90%, yet its composite formula says Supply 70% / Demand 30%. The default follows "
    "the 70/30 formula and rescales the six Supply weights; the \"literal\" row shows the other reading. "
    "**This interpretation still needs sign-off from HPB CIP.**"
)

st.subheader("Rank stability under random re-weighting")
stability = _stability_table(category_scores)
top = stability.head(20)
st.caption(
    "500 random weightings: Supply and Demand sub-weights are drawn around the defaults, and Supply's share "
    "of the index varies between 60% and 80%. The bar shows the 5th–95th percentile rank of each mall."
)
fig = px.scatter(
    top, x="median_rank", y="name", error_x=top["rank_p95"] - top["median_rank"],
    error_x_minus=top["median_rank"] - top["rank_p5"],
    labels={"median_rank": "Rank (median, with 5th–95th percentile range)", "name": ""},
)
fig.update_yaxes(autorange="reversed")
fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")
solid = int((stability.head(10)["pct_top10"] >= 80).sum())
st.markdown(
    f"**{solid} of the default Top 10** stay in the Top 10 in at least 80% of the re-weightings; the rest "
    "are close calls that a small weight change can swap with the next few malls."
)
st.dataframe(
    top[["default_rank", "name", "median_rank", "rank_p5", "rank_p95", "pct_top10", "pct_top20", "pct_top50"]]
    .rename(columns={"default_rank": "Default rank", "name": "Mall", "median_rank": "Median rank",
                     "rank_p5": "Best (p5)", "rank_p95": "Worst (p95)", "pct_top10": "% in Top 10",
                     "pct_top20": "% in Top 20", "pct_top50": "% in Top 50"})
    .style.format({"Median rank": "{:.0f}", "Best (p5)": "{:.0f}", "Worst (p95)": "{:.0f}",
                   "% in Top 10": "{:.0f}", "% in Top 20": "{:.0f}", "% in Top 50": "{:.0f}"}),
    hide_index=True, width="stretch",
)

weights = scoring.DEFAULT_SUPPLY_WEIGHTS
nominal = {k: v / sum(weights.values()) * 100 for k, v in weights.items()}
spread = {k: category_scores[k].std() * weights[k] for k in weights}
effective = {k: v / sum(spread.values()) * 100 for k, v in spread.items()}
st.subheader("Nominal vs effective weight")
st.dataframe(
    pd.DataFrame({
        "Category": [scoring.CATEGORY_LABELS[k] for k in weights],
        "Nominal weight (%)": [round(nominal[k], 1) for k in weights],
        "Effective share of Supply variation (%)": [round(effective[k], 1) for k in weights],
    }),
    hide_index=True, width="stretch",
)
st.caption(
    "A category's weight only matters in proportion to how much malls differ on it. Where the effective share "
    "is well below the nominal weight (typically a category most malls score 0 on, such as Partnership "
    "Readiness), moving its slider changes the ranking less than the label suggests."
)

st.subheader("Do the categories overlap?")
corr_cols = list(scoring.CATEGORY_LABELS)
corr = category_scores[corr_cols].rank().corr().round(2)
corr.index = corr.columns = [scoring.CATEGORY_LABELS[c] for c in corr_cols]
heat = px.imshow(corr, zmin=-1, zmax=1, color_continuous_scale="RdBu_r", text_auto=True, aspect="auto")
heat.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(heat, width="stretch")
st.caption(
    "Rank correlation between categories (1 = move together, 0 = unrelated, −1 = opposite). Two categories "
    "that move together are partly measuring the same thing, so weighting both counts it twice. Engagement Gap "
    "is built to be unrelated to Reach & Population. The supply categories are only modestly related to one "
    "another (dining and healthcare the most), so each adds mostly separate information."
)

if "A_healthier_share" in category_scores.columns:
    with st.expander("Experiment: the charter's \"% of F&B outlets\" for Healthy Dining (not in the index)"):
        reliable = category_scores["A_healthier_share"].notna()
        overshoot = int((category_scores["A_hdp_outlets"] > category_scores["A_fnb_osm_count"]).sum())
        corr = category_scores.loc[reliable, "A_healthier_share"].rank().corr(
            category_scores.loc[reliable, "A_hdp_outlets"].rank())
        st.markdown(
            f"""
The charter wants healthier outlets as a **share** of a mall's F&B outlets. There is no public tenant
directory, so as an experiment we divided HPB healthier-eatery outlets within ~200m by the F&B outlets
OpenStreetMap lists in the same area (restaurants, cafes, fast food, food courts), for the
{int(reliable.sum())} malls with at least 5 mapped F&B outlets.

- It is **not used in the score**: in {overshoot} malls HPB lists *more* healthier outlets than OSM maps F&B
  outlets in total, so OSM is clearly incomplete inside malls and the ratio can exceed 100%.
- Where it can be computed it tracks the plain count closely (rank correlation {corr:.2f}), so it would
  not change the shortlist much until the denominator is better.

The columns `A_hdp_outlets`, `A_fnb_osm_count` and `A_healthier_share` are in `category_scores.csv` for
review. A real tenant count from mall directories or landlords would make this metric usable.
"""
        )
