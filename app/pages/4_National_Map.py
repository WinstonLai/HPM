"""Page 5 - National Map: mall locations coloured by score, candidate shortlist toggle."""
from __future__ import annotations

import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import data_loader  # noqa: E402

st.set_page_config(page_title="National Map | HPM Dashboard", page_icon="🗺️", layout="wide")
st.title("🗺️ National Map")

if not data_loader.data_available():
    st.error("No processed data found. Run `python etl/run_all.py` first.")
    st.stop()

df = data_loader.load_default_index()

shortlist_choice = st.radio(
    "Show", ["All assessed malls", "Top 10 candidates", "Top 20 candidates", "Top 50 candidates"],
    horizontal=True,
)
if shortlist_choice == "Top 10 candidates":
    df = df[df["top10"]]
elif shortlist_choice == "Top 20 candidates":
    df = df[df["top20"]]
elif shortlist_choice == "Top 50 candidates":
    df = df[df["top50"]]

# green (high score) -> red (low score)
lo, hi = df["hpm_index"].min(), df["hpm_index"].max()
span = max(hi - lo, 1e-9)


def score_to_color(score: float) -> list[int]:
    t = (score - lo) / span
    r = int(220 * (1 - t) + 20 * t)
    g = int(60 * (1 - t) + 160 * t)
    b = 60
    return [r, g, b, 200]


df = df.copy()
df["color"] = df["hpm_index"].map(score_to_color)
df["radius"] = 80 + df["hpm_index"] * 3

view_state = pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=10.5, pitch=0)
layer = pdk.Layer(
    "ScatterplotLayer",
    data=df,
    get_position="[lon, lat]",
    get_fill_color="color",
    get_radius="radius",
    pickable=True,
)
tooltip = {"text": "{name}\nRegion: {region}\nScore: {hpm_index}\nTier: {tier}"}
st.pydeck_chart(
    pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip=tooltip,
        map_provider="carto",
        map_style="dark",
    )
)
st.caption("Colour scale: red = lower HPM Index, green = higher HPM Index. "
           f"Showing {len(df)} malls.")
