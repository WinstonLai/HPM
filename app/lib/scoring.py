"""Thin Streamlit-facing wrapper around etl/scoring_formula.py, so every
page's weight sliders recompute the index with the exact same formula the
offline ETL step used to produce the default ranking."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "etl"))

from scoring_formula import (  # noqa: F401,E402
    CATEGORY_LABELS,
    DEFAULT_DEMAND_WEIGHTS,
    DEFAULT_SUPPLY_WEIGHTS,
    add_strategic_quadrant,
    compute_index,
)
