"""What-If Simulator: reweight categories live, ranking updates instantly.
The weights chosen here apply to every other page too (see app/lib/weights.py)."""
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
from safe_text import to_csv_bytes  # noqa: E402

st.set_page_config(page_title="What-If Simulator | HPM Dashboard", page_icon="🎚️", layout="wide")
st.title("🎚️ What-If Simulator")
st.caption(
    "Adjust category weights, the overall Supply/Demand split and the tier cut-offs — the ranking, tiers, "
    "and Top 10/20/50 shortlists below recompute instantly. Your settings carry over to every other page "
    "until you reset them."
)

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

category_scores = data_loader.load_category_scores()


@st.cache_data
def _rank_stability(scores: pd.DataFrame, supply_w: dict, demand_w: dict, supply_block_weight: float) -> pd.DataFrame:
    # 500 random re-weightings: cached so that moving a tier cut-off (which changes no rank) does not redo them
    return scoring.rank_stability(scores, supply_weights=supply_w, demand_weights=demand_w,
                                  supply_block_weight=supply_block_weight)
default_index = data_loader.load_default_index()
defaults = weights.default_settings()
saved = weights.get_settings() or defaults


def _rebalance(changed_key: str, group_keys: list[str]) -> None:
    """on_change callback: keep a slider group summing to exactly 100 by
    redistributing the remaining budget across the other sliders in the
    group, proportional to their current relative weights."""
    new_val = st.session_state[changed_key]
    others = [k for k in group_keys if k != changed_key]
    remaining = 100 - new_val
    others_sum = sum(st.session_state[k] for k in others)

    allocated = 0
    for k in others[:-1]:
        share = round(st.session_state[k] / others_sum * remaining) if others_sum > 0 else remaining // len(others)
        share = max(0, min(remaining - allocated, share))
        st.session_state[k] = share
        allocated += share
    st.session_state[others[-1]] = max(0, remaining - allocated)


def _order_tiers(changed: str) -> None:
    """on_change callback: keep Silver <= Gold <= Platinum by pushing the other
    cut-offs along with the one the user moved, so the sliders always show the
    values that are actually used."""
    s = st.session_state
    if changed == "Platinum":
        s["tier_Gold"] = min(s["tier_Gold"], s["tier_Platinum"])
        s["tier_Silver"] = min(s["tier_Silver"], s["tier_Gold"])
    elif changed == "Gold":
        s["tier_Platinum"] = max(s["tier_Platinum"], s["tier_Gold"])
        s["tier_Silver"] = min(s["tier_Silver"], s["tier_Gold"])
    else:
        s["tier_Gold"] = max(s["tier_Gold"], s["tier_Silver"])
        s["tier_Platinum"] = max(s["tier_Platinum"], s["tier_Gold"])


def linked_weight_sliders(group_keys: list[str], initial: dict, key_prefix: str) -> dict:
    """Render a group of sliders that always sum to 100: moving one
    proportionally redistributes the remaining budget across the rest. Slider
    values are restored from `initial` (the saved settings) when the widgets
    have no state, e.g. after visiting another page."""
    session_keys = [f"{key_prefix}_{col}" for col in group_keys]
    if session_keys[0] not in st.session_state:
        for col, skey in zip(group_keys, session_keys):
            st.session_state[skey] = initial[col]

    out = {}
    for col, skey in zip(group_keys, session_keys):
        st.slider(
            scoring.CATEGORY_LABELS[col], 0, 100, key=skey,
            on_change=_rebalance, args=(skey, session_keys),
        )
        out[col] = st.session_state[skey]
    return out


with st.sidebar:
    st.button("Reset to defaults", on_click=weights.reset, width="stretch")

    st.header("Supply Readiness weights")
    st.caption("Sliders are linked and always sum to 100% — raising one lowers the rest proportionally.")
    supply_sliders = linked_weight_sliders(list(scoring.DEFAULT_SUPPLY_WEIGHTS), saved["supply"], "sw")
    if "exclude_proxies" not in st.session_state:
        st.session_state["exclude_proxies"] = saved["exclude_proxies"]
    exclude_proxy_categories = st.checkbox(
        "Exclude proxy categories (H365 & HPB Engagement, Partnership Readiness)",
        key="exclude_proxies",
        help="These two are stand-ins (community-club proximity, landlord portfolio size), not the "
             "metrics the charter names. Ticking this sets their weight to 0 and re-scales the rest.",
    )

    st.header("Demand Opportunity weights")
    st.caption("Also linked, summing to 100%.")
    demand_sliders = linked_weight_sliders(list(scoring.DEFAULT_DEMAND_WEIGHTS), saved["demand"], "dw")

    st.header("Overall split")
    if "split_supply" not in st.session_state:
        st.session_state["split_supply"] = saved["supply_block"]
    supply_block_weight = st.slider("Supply Readiness weight (%)", 0, 100, key="split_supply")
    demand_block_weight = 100 - supply_block_weight
    st.caption(f"Demand Opportunity weight: **{demand_block_weight}%**")

    st.header("Tier cut-offs")
    st.caption("Minimum HPM Index for each tier. Below Silver is Bronze.")
    for name in ("Platinum", "Gold", "Silver"):
        if f"tier_{name}" not in st.session_state:
            st.session_state[f"tier_{name}"] = int(saved["tiers"][name])
    st.slider("Platinum ≥", 0, 100, key="tier_Platinum", on_change=_order_tiers, args=("Platinum",))
    st.slider("Gold ≥", 0, 100, key="tier_Gold", on_change=_order_tiers, args=("Gold",))
    st.slider("Silver ≥", 0, 100, key="tier_Silver", on_change=_order_tiers, args=("Silver",))
    tier_thresholds = {name: int(st.session_state[f"tier_{name}"]) for name in ("Platinum", "Gold", "Silver")}

settings = {"supply": supply_sliders, "demand": demand_sliders, "supply_block": supply_block_weight,
            "exclude_proxies": exclude_proxy_categories, "tiers": tier_thresholds}
weights.save_settings(**settings)
is_custom = weights.get_settings() is not None
result = weights.compute(category_scores, settings)

if is_custom:
    st.info("Your custom weights are active on every page. Use **Reset to defaults** in the sidebar to undo.", icon="🎚️")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Top 10 cutoff score", f"{result.nsmallest(10, 'rank')['hpm_index'].min():.1f}")
col2.metric("Top 20 cutoff score", f"{result.nsmallest(20, 'rank')['hpm_index'].min():.1f}")
col3.metric("Top 50 cutoff score", f"{result.nsmallest(50, 'rank')['hpm_index'].min():.1f}")
col4.metric("Malls in Gold/Platinum", int(result["tier"].isin(["Gold", "Platinum"]).sum()))

# Movement against the default ranking: positive = moved up.
default_rank = default_index.set_index("mall_id")["rank"]
moved = result["mall_id"].map(default_rank) - result["rank"]


def _arrow(d) -> str:
    if pd.isna(d) or d == 0:
        return "–"
    return f"▲{int(d)}" if d > 0 else f"▼{int(-d)}"


result = result.assign(vs_default=moved.map(_arrow))
display_cols = ["rank", "name", "region", "operator", "hpm_index", "tier", "vs_default"]
rename = {"rank": "Rank", "name": "Mall", "region": "Region", "operator": "Operator",
          "hpm_index": "Score", "tier": "Tier", "vs_default": "vs default rank"}

tab1, tab2, tab3, tab4 = st.tabs(["Top 10", "Top 20", "Top 50", "How stable is this?"])
for tab, n in zip((tab1, tab2, tab3), (10, 20, 50)):
    with tab:
        shortlist = result.nsmallest(n, "rank")[display_cols].rename(columns=rename)
        st.dataframe(
            shortlist.style.format({"Score": "{:.1f}"}),
            hide_index=True,
            width="stretch",
            height=min(38 * (n + 1), 700),
        )
        st.download_button(
            f"Download Top {n} (CSV)", to_csv_bytes(shortlist),
            file_name=f"hpm_top{n}.csv", mime="text/csv", key=f"dl_top{n}",
        )

with tab4:
    supply_w, demand_w = weights.effective_weights(settings)
    stability = _rank_stability(category_scores, supply_w, demand_w, supply_block_weight)
    st.caption(
        "500 random nudges to your current weights (each sub-weight varies, and the Supply share moves up to "
        "±10 points). A mall that stays in the Top 10 in nearly every nudge is a safe pick; one that drops in and "
        "out is a close call that your exact slider settings are deciding."
    )
    top = stability.head(20)
    fig = px.scatter(
        top, x="median_rank", y="name", error_x=top["rank_p95"] - top["median_rank"],
        error_x_minus=top["median_rank"] - top["rank_p5"],
        labels={"median_rank": "Rank (median, with 5th–95th percentile range)", "name": ""},
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")
    solid = int((stability.head(10)["pct_top10"] >= 80).sum())
    st.markdown(f"**{solid} of your Top 10** stay in the Top 10 in at least 80% of the nudges.")
    st.dataframe(
        top[["default_rank", "name", "median_rank", "rank_p5", "rank_p95", "pct_top10", "pct_top20", "pct_top50"]]
        .rename(columns={"default_rank": "Current rank", "name": "Mall", "median_rank": "Median rank",
                         "rank_p5": "Best (p5)", "rank_p95": "Worst (p95)", "pct_top10": "% in Top 10",
                         "pct_top20": "% in Top 20", "pct_top50": "% in Top 50"})
        .style.format({"Median rank": "{:.0f}", "Best (p5)": "{:.0f}", "Worst (p95)": "{:.0f}",
                       "% in Top 10": "{:.0f}", "% in Top 20": "{:.0f}", "% in Top 50": "{:.0f}"}),
        hide_index=True, width="stretch",
    )
