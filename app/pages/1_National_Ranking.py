"""National Ranking: dynamic ranking table with region/operator/tier filters."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
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

# Filters live in widget state under f_* keys and are mirrored to the URL (?q=…&region=…), so a
# filtered view can be bookmarked or shared. Values in the URL are applied once, before the widgets
# are drawn, and ignored if they are not valid options.
OPTIONS = {
    "f_regions": sorted(df["region"].unique()),
    "f_types": sorted(df["type"].unique()) if "type" in df.columns else [],
    "f_operators": sorted(df.loc[known_operator, "operator"].unique()),
    "f_tiers": ["Platinum", "Gold", "Silver", "Bronze"],
}
MULTI_PARAMS = {"region": "f_regions", "type": "f_types", "operator": "f_operators", "tier": "f_tiers"}
FLAG_PARAMS = {"hide_hpm": "f_hide_hpm", "cats": "f_categories"}
if "f_search" not in st.session_state and "q" in st.query_params:
    st.session_state["f_search"] = st.query_params["q"]
for param, key in MULTI_PARAMS.items():
    if key not in st.session_state:
        valid = [v for v in st.query_params.get_all(param) if v in OPTIONS[key]]
        if valid:
            st.session_state[key] = valid
for param, key in FLAG_PARAMS.items():
    if key not in st.session_state and st.query_params.get(param) == "1" and (param != "hide_hpm" or has_hpm_list):
        st.session_state[key] = True


def clear_filters() -> None:
    st.session_state["f_search"] = ""
    for key in OPTIONS:
        st.session_state[key] = []
    st.session_state["f_hide_hpm"] = False


with st.sidebar:
    st.header("Filters")
    search = st.text_input("Search by mall name", placeholder="e.g. Tampines", key="f_search",
                           help="Also matches other names a mall is known by.")
    regions = st.multiselect("Region", OPTIONS["f_regions"], key="f_regions")
    types = st.multiselect("Type", OPTIONS["f_types"], key="f_types") if OPTIONS["f_types"] else []
    operators = st.multiselect(
        "Mall operator", OPTIONS["f_operators"], key="f_operators",
        help="Only malls with a known landlord are listed here.",
    )
    tiers = st.multiselect("Readiness tier", OPTIONS["f_tiers"], key="f_tiers")
    hide_hpm = st.checkbox("Hide existing HPMs", disabled=not has_hpm_list, key="f_hide_hpm",
                           help=None if has_hpm_list else "No existing-HPM list loaded.")
    show_categories = st.checkbox("Show category scores", key="f_categories")
    filters_active = bool(search.strip() or regions or types or operators or tiers or hide_hpm)
    st.button("Clear filters", on_click=clear_filters, disabled=not filters_active, width="stretch")

params: dict = {}
if search.strip():
    params["q"] = search.strip()
for param, selected in (("region", regions), ("type", types), ("operator", operators), ("tier", tiers)):
    if selected:
        params[param] = selected
if hide_hpm:
    params["hide_hpm"] = "1"
if show_categories:
    params["cats"] = "1"
st.query_params.from_dict(params)

filtered = df.copy()
if search.strip():
    needle = search.strip()
    other_names = pd.Series(data_loader.load_aliases().reindex(filtered["mall_id"]).fillna("").to_numpy(),
                            index=filtered.index)
    filtered = filtered[filtered["name"].str.contains(needle, case=False, regex=False)
                        | other_names.str.contains(needle, case=False, regex=False)]
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
column_config[labels["rank"]] = st.column_config.NumberColumn(
    labels["rank"], help=f"1 = highest HPM Index, out of {len(df)} malls (not out of the rows shown).")
column_config[labels["tier"]] = st.column_config.TextColumn(
    labels["tier"], help="Fixed cut-offs on the HPM Index (Platinum, Gold, Silver, otherwise Bronze); "
                         "they can be moved on the What-If Simulator.")
column_config[labels["catchment"]] = st.column_config.TextColumn(
    labels["catchment"], help="Daytime-led: more workers than residents nearby. Residential: the reverse.")
table_height = min(650, 35 * (len(table) + 1) + 3)    # shrink for short results instead of showing blank rows
st.dataframe(table, hide_index=True, width="stretch", height=max(table_height, 105),
             column_config=column_config)
if table.empty:
    st.info("No malls match these filters. Use **Clear filters** in the sidebar to start again.")

st.download_button("Download this table (CSV)", to_csv_bytes(table),
                   file_name="hpm_ranking.csv", mime="text/csv")
if show_categories:
    st.caption("A blank category score means *not applicable*, not zero: for example Engagement Gap for a mall "
               "with no residents nearby. Such a mall's score is worked out from its other factors.")
st.caption(
    "**Catchment**: *Daytime-led* means the area within ~2km has more workers than residents "
    "(CBD, Orchard, airport), where residents-only Reach understates the people around the mall."
)
