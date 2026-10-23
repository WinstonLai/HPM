"""Cached loaders for the ETL pipeline's processed CSVs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def _mtime_ns(path: Path) -> int:
    """Modification time of `path` (0 if it does not exist); part of every cache key below, so a
    re-run ETL shows up in a running dashboard instead of waiting for a restart."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


@st.cache_data
def _read_csv(path: str, mtime_ns: int, usecols: tuple | None = None) -> pd.DataFrame:
    # postal_code is a zero-padded string; read as a number it would lose its leading zeros.
    return pd.read_csv(path, usecols=list(usecols) if usecols else None, dtype={"postal_code": str})


@st.cache_data
def _read_json(path: str, mtime_ns: int) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _csv(name: str, usecols: tuple | None = None) -> pd.DataFrame:
    path = PROCESSED_DIR / name
    return _read_csv(str(path), _mtime_ns(path), usecols)


def load_category_scores() -> pd.DataFrame:
    return _csv("category_scores.csv")


def load_default_index() -> pd.DataFrame:
    return _csv("hpm_index.csv")


def load_meta() -> dict:
    """Provenance written by the ETL (data/processed/_meta.json); {} if absent."""
    path = PROCESSED_DIR / "_meta.json"
    return _read_json(str(path), _mtime_ns(path))


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


def load_aliases() -> pd.Series:
    """Other names each mall is known by (mall_id -> "A; B"), from the registry; empty if unavailable."""
    try:
        return _csv("malls.csv", ("mall_id", "aliases")).set_index("mall_id")["aliases"].fillna("")
    except (OSError, ValueError):
        return pd.Series(dtype=str)
