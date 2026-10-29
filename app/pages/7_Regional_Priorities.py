"""Regional Priorities: which regions have the most high-demand malls still to engage,
how chain and independent landlords compare, and whether the index recognises the malls
already known for health-promotion programmes (the reference malls)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402
import weights  # noqa: E402
from safe_text import escape_html  # noqa: E402

st.set_page_config(page_title="Regional Priorities | Mall Health Dashboard", page_icon="📍", layout="wide")
st.title("📍 Regional Priorities")
st.caption(
    "Where the high-demand malls are, which of them are not yet on the reference list, and how landlord "
    "portfolios compare. Uses your current weights (default unless changed on the What-If Simulator); quadrants split Readiness and Demand at their medians."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df, is_custom = weights.load_index()
weights.show_banner("regional")
df = scoring.add_strategic_quadrant(df)
has_hpm_list = "is_existing_hpm" in df.columns and int(df["is_existing_hpm"].sum()) > 0
if "is_existing_hpm" not in df.columns:
    df["is_existing_hpm"] = 0

# --------------------------------------------------------------------------------
st.header("1. Where to expand")
group_label = st.radio("Group malls by", ["Region", "Planning area"], horizontal=True)
group_col = "region" if group_label == "Region" else "planning_area"
if group_col not in df.columns:
    st.warning("Planning areas are not in the processed data yet — re-run `python etl/build_category_scores.py`.")
    st.stop()

# A "priority" mall is one with high demand (Pioneer: ready now; Strategic Investment: needs
# capability building) that is not already a reference mall.
df["priority"] = df["quadrant"].isin(["Pioneer", "Strategic Investment"]) & (df["is_existing_hpm"] == 0)

summary = (
    df.groupby(group_col)
    .agg(
        malls=("name", "count"),
        avg_index=("hpm_index", "mean"),
        avg_supply=("supply_score", "mean"),
        avg_demand=("demand_score", "mean"),
        pioneer=("quadrant", lambda s: int((s == "Pioneer").sum())),
        strategic=("quadrant", lambda s: int((s == "Strategic Investment").sum())),
        quick_wins=("quadrant", lambda s: int((s == "Quick Wins").sum())),
        existing_hpm=("is_existing_hpm", "sum"),
        priority_malls=("priority", "sum"),
    )
    .reset_index()
    .sort_values(["priority_malls", "avg_demand"], ascending=False)
)

show = summary.rename(columns={
    group_col: group_label, "malls": "Malls", "avg_index": "Avg Health Readiness Index", "avg_supply": "Avg Supply",
    "avg_demand": "Avg Demand", "pioneer": "Pioneer", "strategic": "Strategic Investment",
    "quick_wins": "Quick Wins", "existing_hpm": "Reference malls", "priority_malls": "Priority malls",
})
if not has_hpm_list:
    show = show.drop(columns=["Reference malls"])
st.dataframe(
    show.style.format({"Avg Health Readiness Index": "{:.1f}", "Avg Supply": "{:.1f}", "Avg Demand": "{:.1f}"}),
    hide_index=True, width="stretch",
)
st.caption(
    "**Priority malls** = Pioneer or Strategic Investment (high demand) that are not already a "
    "reference mall. "
    + ("" if has_hpm_list else
       "**No reference-mall list has been loaded**, so every high-demand mall counts as a priority — "
       "add the list to `data/manual/existing_hpm.csv` (see Section 3).")
)

counts = (
    df.groupby([group_col, "quadrant"]).size().reset_index(name="Malls")
)
fig = px.bar(
    counts, x=group_col, y="Malls", color="quadrant",
    category_orders={"quadrant": ["Pioneer", "Strategic Investment", "Quick Wins", "Future Monitoring"]},
    color_discrete_map={"Pioneer": "#0072B2", "Strategic Investment": "#E69F00",
                        "Quick Wins": "#009E73", "Future Monitoring": "#999999"},
    labels={group_col: group_label, "quadrant": "Quadrant"},
)
fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.25))
st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------------
st.header("2. Chain vs independent landlords")
known = df[df["operator"] != "Unknown"]
portfolio = known.groupby("operator")["name"].transform("count")
df["landlord_group"] = "Unknown landlord"
df.loc[known.index, "landlord_group"] = portfolio.map(
    lambda n: "Portfolio of 2+ malls" if n >= 2 else "Single-mall landlord"
)
order = ["Portfolio of 2+ malls", "Single-mall landlord", "Unknown landlord"]

cat_cols = [c for c in scoring.DEFAULT_SUPPLY_WEIGHTS] + [c for c in scoring.DEFAULT_DEMAND_WEIGHTS]
by_group = df.groupby("landlord_group")[["hpm_index", "supply_score", "demand_score"] + cat_cols].mean()
by_group.insert(0, "Malls", df.groupby("landlord_group").size())
by_group = by_group.reindex(order).dropna(how="all")
by_group = by_group.rename(columns={
    "hpm_index": "Health Readiness Index", "supply_score": "Supply", "demand_score": "Demand", **scoring.CATEGORY_LABELS,
})
st.dataframe(by_group.style.format("{:.1f}", subset=by_group.columns[1:]), width="stretch")

df["hover_label"] = df["name"].map(escape_html)    # Plotly hover text is pseudo-HTML
box = px.box(df, x="landlord_group", y="hpm_index", category_orders={"landlord_group": order},
             points="all", hover_name="hover_label",
             labels={"landlord_group": "", "hpm_index": "Health Readiness Index"})
box.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(box, width="stretch")
st.caption(
    f"A landlord was identified for {len(known)} of {len(df)} malls. **\"Unknown landlord\" does not mean "
    "independent** — it means Wikipedia did not name one — so read the comparison as indicative only. "
    "Landlord groups can be corrected in `data/manual/operator_aliases.csv` and `data/manual/operators.csv`."
)

# --------------------------------------------------------------------------------
st.header("3. Do reference malls score higher?")
result = scoring.hpm_backtest(df)
if result is None:
    st.info(
        "A useful check is whether malls already known for health-promotion programmes score higher than other malls. "
        "That needs a list of such malls, which is not public. Add it as "
        "`data/manual/existing_hpm.csv` (columns `name,source`), then run "
        "`python etl/build_category_scores.py && python etl/build_index.py`. This section will then show "
        "where those malls rank and how well the index separates them from the rest."
    )
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reference malls matched", result["n_existing_hpm"])
    c2.metric("Median rank", f"{result['median_rank']:.0f} of {len(df)}")
    c3.metric("In the Top 20 / Top 50", f"{result['in_top20']} / {result['in_top50']}")
    c4.metric("AUC", f"{result['auc']:.2f}",
              help="Chance that a random reference mall outscores a random other mall. 0.5 = no better than chance.")
    st.dataframe(
        df[df["is_existing_hpm"] == 1][["rank", "name", "region", "hpm_index", "supply_score", "demand_score", "tier"]]
        .rename(columns={"rank": "Rank", "name": "Mall", "region": "Region", "hpm_index": "Health Readiness Index",
                         "supply_score": "Supply", "demand_score": "Demand", "tier": "Tier"})
        .style.format({"Health Readiness Index": "{:.1f}", "Supply": "{:.1f}", "Demand": "{:.1f}"}),
        hide_index=True, width="stretch",
    )
    st.caption("An AUC well above 0.5 supports the index; near 0.5 means it does not recognise the reference malls.")

    st.subheader("Which components recognise reference malls?")
    auc = scoring.component_auc(df)
    labels = {"hpm_index": "Health Readiness Index", "supply_score": "Supply Readiness", "demand_score": "Demand Opportunity",
              **scoring.CATEGORY_LABELS}
    auc_table = pd.DataFrame({"Component": [labels[c] for c in auc.index], "AUC": auc.values})
    bar = px.bar(auc_table, x="AUC", y="Component", orientation="h", range_x=[0.3, 1.0])
    bar.add_vline(x=0.5, line_dash="dash", line_color="gray", annotation_text="chance")
    bar.update_yaxes(autorange="reversed")
    bar.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(bar, width="stretch")
    st.caption(
        "**Read with care.** This asks whether the index *resembles* the reference list, not whether it "
        "predicts readiness. Healthy Dining is built from national Healthier Dining datasets, so malls that "
        "are already reference malls likely score well on it partly because they already take part in those programmes. "
        "Components near 0.5 (such as Accessibility or Physical Activity) do not distinguish reference malls "
        "from other malls."
    )

st.header("4. Candidate malls: highest-ranked, not a reference mall")
n_show = st.slider("Show the top", 5, 40, 15)
candidates = df[df["is_existing_hpm"] == 0].sort_values("rank").head(n_show)
st.dataframe(
    candidates[["rank", "name", "region", "operator", "hpm_index", "supply_score", "demand_score", "quadrant"]]
    .rename(columns={"rank": "Rank", "name": "Mall", "region": "Region", "operator": "Operator",
                     "hpm_index": "Health Readiness Index", "supply_score": "Supply", "demand_score": "Demand",
                     "quadrant": "Quadrant"})
    .style.format({"Health Readiness Index": "{:.1f}", "Supply": "{:.1f}", "Demand": "{:.1f}"}),
    hide_index=True, width="stretch",
)
st.caption(
    "A starting shortlist: malls the index ranks highest that are not on the reference-mall "
    "list. Rank is out of all malls, including reference malls." if has_hpm_list else
    "Load the reference-mall list (Section 3) to exclude malls already on it."
)
