"""Page 5 - National Map: mall locations coloured by score, candidate shortlist toggle."""
from __future__ import annotations

import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402
import weights  # noqa: E402
from safe_text import escape_html, escape_md  # noqa: E402

st.set_page_config(page_title="National Map | HPM Dashboard", page_icon="🗺️", layout="wide")
st.title("🗺️ National Map")

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df, is_custom = weights.load_index()
weights.show_banner("map")
has_hpm_list = "is_existing_hpm" in df.columns and int(df["is_existing_hpm"].sum()) > 0

# Sequential, colour-blind-safe scale (light yellow -> dark blue), stretched over
# ALL assessed malls so the shortlist toggle only changes which points are shown,
# not how their colours are stretched.
STOPS = [(255, 255, 204), (161, 218, 180), (65, 182, 196), (44, 127, 184), (37, 52, 148)]
lo, hi = df["hpm_index"].min(), df["hpm_index"].max()
span = max(hi - lo, 1e-9)


def score_to_color(score: float) -> list[int]:
    t = min(max((score - lo) / span, 0.0), 1.0) * (len(STOPS) - 1)
    i = min(int(t), len(STOPS) - 2)
    f = t - i
    r, g, b = (int(STOPS[i][k] * (1 - f) + STOPS[i + 1][k] * f) for k in range(3))
    return [r, g, b, 230]


left, right = st.columns([3, 2])
with left:
    shortlist_choice = st.radio(
        "Show", ["All assessed malls", "Top 10 candidates", "Top 20 candidates", "Top 50 candidates"],
        horizontal=True,
    )
with right:
    highlight_hpm = st.checkbox("Ring existing HPMs", value=has_hpm_list, disabled=not has_hpm_list,
                                help=None if has_hpm_list else "No existing-HPM list loaded.")

shown = df
if shortlist_choice == "Top 10 candidates":
    shown = df[df["top10"]]
elif shortlist_choice == "Top 20 candidates":
    shown = df[df["top20"]]
elif shortlist_choice == "Top 50 candidates":
    shown = df[df["top50"]]
shown = shown.copy()

focus = st.selectbox("Zoom to a mall", ["(whole of Singapore)"] + sorted(shown["name"]))
shown["color"] = shown["hpm_index"].map(score_to_color)
shown["radius"] = 120 + shown["hpm_index"] * 3          # metres
shown["score_label"] = shown["hpm_index"].map("{:.1f}".format)
shown["supply_label"] = shown["supply_score"].map("{:.1f}".format)
shown["demand_label"] = shown["demand_score"].map("{:.1f}".format)
# The tooltip is rendered as HTML, so scraped text must be escaped first.
shown["tip_name"] = shown["name"].map(escape_html)
shown["tip_region"] = shown["region"].map(escape_html)

if focus == "(whole of Singapore)":
    view_state = pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=10.5, pitch=0)
else:
    sel = shown[shown["name"] == focus].iloc[0]
    view_state = pdk.ViewState(latitude=float(sel["lat"]), longitude=float(sel["lon"]), zoom=14, pitch=0)

layers = [pdk.Layer(
    "ScatterplotLayer", data=shown, get_position="[lon, lat]", get_fill_color="color", get_radius="radius",
    radius_min_pixels=6, radius_max_pixels=22,
    stroked=True, get_line_color=[40, 40, 40, 255], line_width_min_pixels=1, pickable=True,
)]
if highlight_hpm:
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=shown[shown["is_existing_hpm"] == 1], get_position="[lon, lat]",
        filled=False, stroked=True, get_line_color=[230, 120, 0, 255], line_width_min_pixels=3,
        get_radius="radius * 1.0", radius_min_pixels=10, radius_max_pixels=28, pickable=False,
    ))
tooltip = {
    "html": "<b>{tip_name}</b><br/>Rank {rank} · Score {score_label} · {tier}<br/>"
            "Supply {supply_label} · Demand {demand_label}<br/>{tip_region}",
    "style": {"backgroundColor": "#1f2937", "color": "white"},
}
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view_state, tooltip=tooltip,
                         map_provider="carto", map_style="light"))

gradient = ", ".join(f"rgb({r},{g},{b})" for r, g, b in STOPS)
st.markdown(
    f"<div style='display:flex;align-items:center;gap:8px;font-size:0.85rem'>"
    f"<span>{lo:.0f}</span>"
    f"<div style='height:12px;width:240px;border:1px solid #888;background:linear-gradient(90deg,{gradient})'></div>"
    f"<span>{hi:.0f}</span><span style='margin-left:8px'>HPM Index (low → high)</span>"
    + ("<span style='margin-left:16px;color:#e67800'>◯ existing HPM</span>" if highlight_hpm else "")
    + "</div>",
    unsafe_allow_html=True,
)
st.caption(f"Showing {len(shown)} malls. Marker size grows with score. Hover for details.")

if focus != "(whole of Singapore)":
    sel = shown[shown["name"] == focus].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rank", f"{int(sel['rank'])} of {len(df)}")
    c2.metric("HPM Index", f"{sel['hpm_index']:.1f}", help=f"Tier: {sel['tier']}")
    c3.metric("Supply", f"{sel['supply_score']:.1f}")
    c4.metric("Demand", f"{sel['demand_score']:.1f}")
    st.caption(f"{escape_md(sel['region'])} · {escape_md(sel['operator'])}" + (" · existing HPM" if has_hpm_list and sel["is_existing_hpm"] == 1 else ""))
