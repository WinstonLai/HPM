"""Cached loaders for the ETL pipeline's processed CSVs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


@st.cache_data
def load_category_scores() -> pd.DataFrame:
    return pd.read_csv(PROCESSED_DIR / "category_scores.csv")


@st.cache_data
def load_default_index() -> pd.DataFrame:
    return pd.read_csv(PROCESSED_DIR / "hpm_index.csv")


@st.cache_data
def load_meta() -> dict:
    """Provenance written by the ETL (data/processed/_meta.json); {} if absent."""
    path = PROCESSED_DIR / "_meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def data_available() -> bool:
    return (PROCESSED_DIR / "category_scores.csv").exists() and (PROCESSED_DIR / "hpm_index.csv").exists()


def data_age_days() -> int | None:
    """Days since the raw datasets were last fetched (or the scores built); None if unknown."""
    meta = load_meta()
    stamp = meta.get("raw_data", {}).get("latest_fetch") or meta.get("category_scores", {}).get("built_at")
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - when).days, 0)


@st.cache_data
def load_aliases() -> pd.Series:
    """Other names each mall is known by (mall_id -> "A; B"), from the registry; empty if unavailable."""
    path = PROCESSED_DIR / "malls.csv"
    try:
        return pd.read_csv(path, usecols=["mall_id", "aliases"]).set_index("mall_id")["aliases"].fillna("")
    except (OSError, ValueError):
        return pd.Series(dtype=str)
