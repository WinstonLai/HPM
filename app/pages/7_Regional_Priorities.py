"""Page 7 - Regional Priorities: where should HPB expand next, how do chain
and independent landlords compare, and does the index recognise the malls that
are already Health Promoting Malls? (Charter objectives: "identify regions that
should be prioritised for HPM expansion", "differences across mall chains and
independent malls", "whether existing HPMs demonstrate stronger attributes".)"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402

st.set_page_config(page_title="Regional Priorities | HPM Dashboard", page_icon="📍", layout="wide")
st.title("📍 Regional Priorities")
st.caption(
    "Where the high-demand malls are, which of them HPB has not yet reached, and how landlord "
    "portfolios compare. Uses the default weights; quadrants split Readiness and Demand at their medians."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df = scoring.add_strategic_quadrant(data_loader.load_default_index())
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

# A "priority" mall is one with high demand (Pioneer HPM: ready now; Strategic Investment: needs
# capability building) that is not already a Health Promoting Mall.
df["priority"] = df["quadrant"].isin(["Pioneer HPM", "Strategic Investment"]) & (df["is_existing_hpm"] == 0)

summary = (
    df.groupby(group_col)
    .agg(
        malls=("name", "count"),
        avg_index=("hpm_index", "mean"),
        avg_supply=("supply_score", "mean"),
        avg_demand=("demand_score", "mean"),
        pioneer=("quadrant", lambda s: int((s == "Pioneer HPM").sum())),
        strategic=("quadrant", lambda s: int((s == "Strategic Investment").sum())),
        quick_wins=("quadrant", lambda s: int((s == "Quick Wins").sum())),
        existing_hpm=("is_existing_hpm", "sum"),
        priority_malls=("priority", "sum"),
    )
    .reset_index()
    .sort_values(["priority_malls", "avg_demand"], ascending=False)
)

show = summary.rename(columns={
    group_col: group_label, "malls": "Malls", "avg_index": "Avg HPM Index", "avg_supply": "Avg Supply",
    "avg_demand": "Avg Demand", "pioneer": "Pioneer HPM", "strategic": "Strategic Investment",
    "quick_wins": "Quick Wins", "existing_hpm": "Existing HPMs", "priority_malls": "Priority malls",
})
if not has_hpm_list:
    show = show.drop(columns=["Existing HPMs"])
st.dataframe(
    show.style.format({"Avg HPM Index": "{:.1f}", "Avg Supply": "{:.1f}", "Avg Demand": "{:.1f}"}),
    hide_index=True, use_container_width=True,
)
st.caption(
    "**Priority malls** = Pioneer HPM or Strategic Investment (high demand) that are not already a "
    "Health Promoting Mall. "
    + ("" if has_hpm_list else
       "**No list of existing HPMs has been loaded**, so every high-demand mall counts as a priority — "
       "add the list to `data/manual/existing_hpm.csv` (see Section 3).")
)

counts = (
    df.groupby([group_col, "quadrant"]).size().reset_index(name="Malls")
)
fig = px.bar(
    counts, x=group_col, y="Malls", color="quadrant",
    category_orders={"quadrant": ["Pioneer HPM", "Strategic Investment", "Quick Wins", "Future Monitoring"]},
    color_discrete_map={"Pioneer HPM": "#0072B2", "Strategic Investment": "#E69F00",
                        "Quick Wins": "#009E73", "Future Monitoring": "#999999"},
    labels={group_col: group_label, "quadrant": "Quadrant"},
)
fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.25))
st.plotly_chart(fig, use_container_width=True)

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
    "hpm_index": "HPM Index", "supply_score": "Supply", "demand_score": "Demand", **scoring.CATEGORY_LABELS,
})
st.dataframe(by_group.style.format("{:.1f}", subset=by_group.columns[1:]), use_container_width=True)

box = px.box(df, x="landlord_group", y="hpm_index", category_orders={"landlord_group": order},
             points="all", hover_name="name",
             labels={"landlord_group": "", "hpm_index": "HPM Index"})
box.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(box, use_container_width=True)
st.caption(
    f"A landlord was identified for {len(known)} of {len(df)} malls. **\"Unknown landlord\" does not mean "
    "independent** — it means Wikipedia did not name one — so read the comparison as indicative only. "
    "Landlord groups can be corrected in `data/manual/operator_aliases.csv` and `data/manual/operators.csv`."
)

# --------------------------------------------------------------------------------
st.header("3. Do existing Health Promoting Malls score higher?")
result = scoring.hpm_backtest(df)
if result is None:
    st.info(
        "The charter asks whether existing HPMs show stronger health-promoting attributes than other malls. "
        "That needs the list of malls HPB has already designated, which is not public. Add it as "
        "`data/manual/existing_hpm.csv` (columns `name,source`), then run "
        "`python etl/build_category_scores.py && python etl/build_index.py`. This section will then show "
        "where those malls rank and how well the index separates them from the rest."
    )
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Existing HPMs matched", result["n_existing_hpm"])
    c2.metric("Median rank", f"{result['median_rank']:.0f} of {len(df)}")
    c3.metric("In the Top 20 / Top 50", f"{result['in_top20']} / {result['in_top50']}")
    c4.metric("AUC", f"{result['auc']:.2f}",
              help="Chance that a random existing HPM outscores a random other mall. 0.5 = no better than chance.")
    st.dataframe(
        df[df["is_existing_hpm"] == 1][["rank", "name", "region", "hpm_index", "supply_score", "demand_score", "tier"]]
        .rename(columns={"rank": "Rank", "name": "Mall", "region": "Region", "hpm_index": "HPM Index",
                         "supply_score": "Supply", "demand_score": "Demand", "tier": "Tier"})
        .style.format({"HPM Index": "{:.1f}", "Supply": "{:.1f}", "Demand": "{:.1f}"}),
        hide_index=True, use_container_width=True,
    )
    st.caption("An AUC well above 0.5 supports the index; near 0.5 means it does not recognise HPB's existing choices.")
