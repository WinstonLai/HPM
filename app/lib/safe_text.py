"""Escaping for text that came from scraped sources (mall names, landlords,
regions), wherever the dashboard renders it as something other than plain text:
markdown, HTML (map tooltip, Plotly labels) and CSV downloads."""
from __future__ import annotations

import html
import re

import pandas as pd

_MD_SPECIAL_RE = re.compile(r"([\\`*_\[\]()<>~$!#|&:])")
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_md(text) -> str:
    """Backslash-escape markdown/LaTeX/emoji-shortcode/colour-directive syntax so `text` shows literally."""
    return _MD_SPECIAL_RE.sub(r"\\\1", "" if pd.isna(text) else str(text))


def escape_html(text) -> str:
    """HTML-escape `text` for HTML-rendering widgets (pydeck tooltips, Plotly labels and hover text)."""
    return html.escape("" if pd.isna(text) else str(text), quote=True)


def csv_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of `df` for export where text cells that spreadsheet apps would run as a
    formula (leading = + - @) get a leading apostrophe. Numeric columns are untouched."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(
                lambda v: "'" + v if isinstance(v, str) and v.startswith(_CSV_FORMULA_PREFIXES) else v)
    return out


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """UTF-8 CSV of `df` for st.download_button, made safe to open in a spreadsheet."""
    return csv_safe(df).to_csv(index=False).encode("utf-8")
