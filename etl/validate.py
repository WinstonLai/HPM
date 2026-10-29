"""Sanity checks that run inside the ETL, so a bad scrape or a bad join fails
loudly instead of quietly producing a plausible-looking ranking.

Each `validate_*` returns (errors, warnings). Errors mean the data should not
be published; warnings are suspicious but possibly legitimate. `enforce`
prints warnings and raises on errors.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from onemap import SG_LAT_RANGE, SG_LON_RANGE, name_tokens

POSTAL_OK = re.compile(r"^\d{6}$")
# Words that carry no identity when comparing a mall's name to its address.
_GENERIC = {"mall", "centre", "center", "shopping", "plaza", "complex", "building", "town", "square",
            "point", "city", "hub", "place", "singapore", "the"}


def validate_registry(malls: pd.DataFrame) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if malls.empty:
        return ["registry is empty"], warnings

    out_of_box = malls[~malls["lat"].between(*SG_LAT_RANGE) | ~malls["lon"].between(*SG_LON_RANGE)]
    if len(out_of_box):
        errors.append(f"{len(out_of_box)} malls outside Singapore: {out_of_box['name'].tolist()[:5]}")
    for col in ("mall_id", "name"):
        dup = malls[malls[col].duplicated(keep=False)][col].unique().tolist()
        if dup:
            errors.append(f"duplicate {col}: {dup[:5]}")
    same_spot = malls[malls.duplicated(["lat", "lon"], keep=False)]["name"].tolist()
    if same_spot:
        errors.append(f"malls sharing exactly one coordinate (duplicate or bad geocode): {same_spot[:6]}")
    if "postal_code" in malls.columns:
        postal = malls["postal_code"].dropna().astype(str)
        bad = postal[~postal.str.match(POSTAL_OK)]
        if len(bad):
            errors.append(f"{len(bad)} postal codes are not 6 digits (leading zeros lost?): {bad.tolist()[:5]}")

    # Does the geocoded address still look like the mall? (Warning only: manual
    # overrides legitimately resolve to an address with a different building name.)
    if "address" in malls.columns:
        mismatched = []
        for r in malls.itertuples():
            want = {t for t in name_tokens(r.name) if t not in _GENERIC and len(t) > 1}
            have = set(name_tokens(str(r.address)))
            if want and not (want & have):
                mismatched.append(r.name)
        if mismatched:
            warnings.append(f"{len(mismatched)} malls whose name shares no word with their geocoded address: "
                            f"{mismatched[:8]}")
    return errors, warnings


def validate_scores(scores: pd.DataFrame, n_malls: int, allow_constant: bool = False) -> tuple[list[str], list[str]]:
    """A constant score column almost always means its source file failed to load,
    so it is an error unless `allow_constant` (e.g. a deliberate partial run)."""
    errors: list[str] = []
    warnings: list[str] = []
    if len(scores) != n_malls:
        errors.append(f"{len(scores)} scored malls but {n_malls} in the registry")
    score_cols = [c for c in scores.columns if c.endswith("_score")]
    for col in score_cols:
        vals = scores[col]
        if col == "engagement_gap_score":      # NaN = no residents nearby ("n/a")
            if vals.isna().mean() > 0.05:
                msg = f"engagement_gap_score is n/a for {vals.isna().mean():.0%} of malls"
                (warnings if allow_constant else errors).append(msg)
            vals = vals.dropna()
        elif vals.isna().any():
            errors.append(f"{col} has {int(vals.isna().sum())} missing values")
        if len(vals) and (vals.min() < -1e-9 or vals.max() > 100 + 1e-9):
            errors.append(f"{col} outside 0-100: [{vals.min():.2f}, {vals.max():.2f}]")
    count_cols = [c for c in scores.columns if c.endswith("_count")]
    neg = [c for c in count_cols if (scores[c] < 0).any()]
    if neg:
        errors.append(f"negative counts in {neg}")
    for col in score_cols:
        if col != "engagement_gap_score" and scores[col].nunique() <= 1:
            msg = f"{col} is constant: its source data probably failed to load"
            (warnings if allow_constant else errors).append(msg)
    return errors, warnings


def validate_index(index: pd.DataFrame) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if not index["rank"].is_unique:
        errors.append("ranks are not unique")
    if sorted(index["rank"]) != list(range(1, len(index) + 1)):
        errors.append("ranks are not 1..n")
    if index["tier"].isna().any():
        errors.append("some malls have no tier")
    if index["hpm_index"].isna().any():
        errors.append("some malls have no HPM index")
    return errors, []


def enforce(stage: str, errors: list[str], warnings: list[str]) -> None:
    for w in warnings:
        print(f"  [check:{stage}] warning: {w}")
    if errors:
        raise ValueError(f"{stage} failed validation:\n  - " + "\n  - ".join(errors))
    print(f"  [check:{stage}] ok ({len(warnings)} warnings)")
