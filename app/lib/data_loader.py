"""Cached loaders for the ETL pipeline's processed CSVs."""
from __future__ import annotations

import json
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
