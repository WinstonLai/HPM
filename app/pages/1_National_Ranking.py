"""Page 2 - National Ranking: dynamic ranking table with region/operator/tier filters."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import scoring  # noqa: E402
import weights  # noqa: E402
from safe_text import to_csv_bytes  # noqa: E402

st.set_page_config(page_title="National Ranking | HPM Dashboard", page_icon="📋", layout="wide")
st.title("📋 National Ranking")

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df, is_custom = weights.load_index()
weights.show_banner("ranking")
has_hpm_list = "is_existing_hpm" in df.columns and int(df["is_existing_hpm"].sum()) > 0
known_operator = df["operator"] != "Unknown"

with st.sidebar:
    st.header("Filters")
    search = st.text_input("Search by mall name", placeholder="e.g. Tampines")
    regions = st.multiselect("Region", sorted(df["region"].unique()))
    types = st.multiselect("Type", sorted(df["type"].unique())) if "type" in df.columns else []
    operators = st.multiselect(
        "Mall operator", sorted(df.loc[known_operator, "operator"].unique()),
        help="Only malls with a known landlord are listed here.",
    )
    tiers = st.multiselect("Readiness tier", ["Platinum", "Gold", "Silver", "Bronze"])
    hide_hpm = st.checkbox("Hide existing HPMs", disabled=not has_hpm_list,
                           help=None if has_hpm_list else "No existing-HPM list loaded.")
    show_categories = st.checkbox("Show category scores")

filtered = df.copy()
if search.strip():
    filtered = filtered[filtered["name"].str.contains(search.strip(), case=False, regex=False)]
if regions:
    filtered = filtered[filtered["region"].isin(regions)]
if types:
    filtered = filtered[filtered["type"].isin(types)]
if operators:
    filtered = filtered[filtered["operator"].isin(operators)]
if tiers:
    filtered = filtered[filtered["tier"].isin(tiers)]
if hide_hpm:
    filtered = filtered[filtered["is_existing_hpm"] == 0]

st.caption(
    f"Showing {len(filtered)} of {len(df)} malls "
    f"({'your custom weights' if is_custom else 'default illustrative weights'} — change them on the "
    f"What-If Simulator page). A landlord is known for {int(known_operator.sum())} of {len(df)} malls; "
    "the rest are \"Unknown\", which does not mean independent."
)

filtered = filtered.assign(
    catchment=filtered["daytime_led"].map({1: "Daytime-led", 0: "Residential"}) if "daytime_led" in filtered else "",
    existing_hpm=filtered["is_existing_hpm"].map({1: "✓", 0: ""}) if has_hpm_list else "",
)
columns = ["rank", "name", "region"] + (["type"] if "type" in filtered.columns else []) + [
    "operator", "hpm_index", "tier", "supply_score", "demand_score", "catchment"]
if has_hpm_list:
    columns.append("existing_hpm")
if show_categories:
    columns += list(scoring.CATEGORY_LABELS)

labels = {"rank": "Rank", "name": "Mall", "region": "Region", "type": "Type", "operator": "Operator",
          "hpm_index": "Score", "tier": "Tier", "supply_score": "Supply Readiness",
          "demand_score": "Demand Opportunity", "catchment": "Catchment", "existing_hpm": "Existing HPM",
          **scoring.CATEGORY_LABELS}
table = filtered[columns].rename(columns=labels)

bar = lambda label: st.column_config.ProgressColumn(label, min_value=0, max_value=100, format="%.1f")  # noqa: E731
column_config = {labels[c]: bar(labels[c]) for c in
                 ["hpm_index", "supply_score", "demand_score"] + (list(scoring.CATEGORY_LABELS) if show_categories else [])}
st.dataframe(table, hide_index=True, width="stretch", height=650, column_config=column_config)

st.download_button("Download this table (CSV)", to_csv_bytes(table),
                   file_name="hpm_ranking.csv", mime="text/csv")
st.caption(
    "**Catchment**: *Daytime-led* means the area within ~2km has more workers than residents "
    "(CBD, Orchard, airport), where residents-only Reach understates the people around the mall."
)
