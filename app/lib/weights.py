"""Custom weights chosen on the What-If Simulator, shared by every page.

Streamlit drops a widget's value from `st.session_state` when the page that
owns the widget is not rendered, so slider values alone would reset as soon as
the user navigated away -- and the other pages, which read the precomputed
default ranking, would never see them. The simulator therefore also saves the
chosen settings under a plain (non-widget) session key. Every page calls
`load_index()` to get the ranking under whatever weights are active, and
`show_banner()` to say so.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import data_loader
import scoring

STATE_KEY = "custom_weights"
# Widget keys the simulator owns; cleared on reset so sliders return to defaults.
WIDGET_PREFIXES = ("sw_", "dw_", "split_supply", "exclude_proxies", "tier_")


def integerize_to_100(weights: dict) -> dict:
    """Largest-remainder rounding: arbitrary positive weights -> integers that
    sum to exactly 100 (naive round() can drift, e.g. three 33.33s give 99)."""
    keys = list(weights.keys())
    total = sum(weights.values()) or 1.0
    scaled = [weights[k] / total * 100 for k in keys]
    floors = [int(x) for x in scaled]
    order = sorted(range(len(keys)), key=lambda i: scaled[i] - floors[i], reverse=True)
    for i in range(100 - sum(floors)):
        floors[order[i]] += 1
    return {keys[i]: floors[i] for i in range(len(keys))}


def default_settings() -> dict:
    """The settings the simulator starts from (slider-friendly integers)."""
    return {
        "supply": integerize_to_100(scoring.DEFAULT_SUPPLY_WEIGHTS),
        "demand": integerize_to_100(scoring.DEFAULT_DEMAND_WEIGHTS),
        "supply_block": int(scoring.SUPPLY_BLOCK_WEIGHT),
        "exclude_proxies": False,
        "tiers": dict(scoring.TIER_THRESHOLDS),
    }


def get_settings() -> dict | None:
    """The active custom settings, or None when everything is at its default."""
    return st.session_state.get(STATE_KEY)


def save_settings(supply: dict, demand: dict, supply_block: int,
                  exclude_proxies: bool, tiers: dict) -> None:
    """Remember the simulator's settings, or forget them if they equal the
    defaults (so unchanged sliders do not mark the whole app as 'custom')."""
    current = {"supply": dict(supply), "demand": dict(demand), "supply_block": int(supply_block),
               "exclude_proxies": bool(exclude_proxies), "tiers": dict(tiers)}
    if current == default_settings():
        st.session_state.pop(STATE_KEY, None)
    else:
        st.session_state[STATE_KEY] = current


def reset() -> None:
    """Back to the defaults everywhere. Safe as an on_click callback."""
    st.session_state.pop(STATE_KEY, None)
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(WIDGET_PREFIXES):
            del st.session_state[key]


def effective_weights(settings: dict) -> tuple[dict, dict]:
    """(supply_weights, demand_weights) for scoring. When a block still sits at
    its slider defaults the exact charter-derived weights are used, not the
    integer-rounded slider values, so unchanged blocks do not drift."""
    defaults = default_settings()
    supply = (scoring.DEFAULT_SUPPLY_WEIGHTS if settings["supply"] == defaults["supply"]
              else dict(settings["supply"]))
    demand = (scoring.DEFAULT_DEMAND_WEIGHTS if settings["demand"] == defaults["demand"]
              else dict(settings["demand"]))
    if settings["exclude_proxies"]:
        supply = scoring.exclude_proxies(supply)
    return supply, demand


def compute(category_scores: pd.DataFrame, settings: dict) -> pd.DataFrame:
    supply, demand = effective_weights(settings)
    return scoring.compute_index(
        category_scores, supply_weights=supply, demand_weights=demand,
        supply_block_weight=settings["supply_block"], demand_block_weight=100 - settings["supply_block"],
        tier_thresholds=settings["tiers"],
    )


def load_index() -> tuple[pd.DataFrame, bool]:
    """(ranking, is_custom). The precomputed default ranking unless the user
    has changed weights on the What-If Simulator in this session."""
    settings = get_settings()
    if settings is None:
        return data_loader.load_default_index(), False
    try:
        return compute(data_loader.load_category_scores(), settings), True
    except Exception as exc:  # noqa: BLE001 -- never leave every page unusable behind bad saved settings
        reset()
        st.warning(f"Your custom weights could not be applied ({exc}), so they were reset to the defaults.")
        return data_loader.load_default_index(), False


def show_banner(key: str) -> None:
    """Tell the user the numbers on this page use their custom weights. The status and the
    reset button sit at the top of the sidebar, in the same place on every page; the notice
    in the page body is for narrow screens, where the sidebar is collapsed."""
    if get_settings() is None:
        return
    st.info("Showing your **custom weights** from the What-If Simulator, not the defaults. "
            "Reset them from the sidebar.", icon="🎚️")
    with st.sidebar:
        st.warning("Custom weights are active", icon="🎚️")
        st.button("Reset to defaults", key=f"reset_{key}", on_click=reset, width="stretch")
