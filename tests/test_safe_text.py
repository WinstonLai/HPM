import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP / "lib"))

import build_mall_registry as registry  # noqa: E402
import data_loader  # noqa: E402
from safe_text import csv_safe, escape_html, escape_md, to_csv_bytes  # noqa: E402

HOSTILE = '<img src=x onerror=alert(1)> *bold* [x](http://evil) $y$ :red[z]'


def test_escape_html_neutralises_tags_and_quotes():
    out = escape_html(HOSTILE + '"')
    assert "<" not in out and ">" not in out and "&lt;img" in out and "&quot;" in out
    assert escape_html(None) == escape_html(float("nan")) == ""


def test_escape_md_makes_markdown_literal():
    out = escape_md(HOSTILE)
    for ch in "*[]()<>$":
        assert all(out[i - 1] == "\\" for i, c in enumerate(out) if c == ch and i), ch
    assert escape_md("People's Park") == "People's Park"        # ordinary names are unchanged
    assert escape_md(float("nan")) == ""


def test_csv_safe_defuses_formulas_but_not_numbers_or_ordinary_text():
    df = pd.DataFrame({"name": ["=HYPERLINK(\"http://x\")", "+1", "-x", "@sum", "Bugis+", "Unknown"],
                       "score": [-1.5, 2.0, 3.0, 4.0, 5.0, 6.0]})
    out = csv_safe(df)
    assert out["name"].tolist() == ["'=HYPERLINK(\"http://x\")", "'+1", "'-x", "'@sum", "Bugis+", "Unknown"]
    assert out["score"].tolist() == df["score"].tolist()
    assert df["name"][0].startswith("=")                         # input not modified
    assert b"'=HYPERLINK" in to_csv_bytes(df)


def test_sanitize_text_strips_wikitext_and_html():
    assert registry.sanitize_text("''Foo'' <ref name=a>x</ref> {{cn}} [[Bar|Baz]] <b>Qux</b> | [link]") == "Foo Baz Qux link"
    assert registry.sanitize_text("<script>alert(1)</script>Plaza") == "alert(1)Plaza"
    assert registry.sanitize_text("People's Park Centre") == "People's Park Centre"
    assert registry.sanitize_text(None) == ""


def test_extract_operator_is_plain_text():
    wikitext = "| owner = [[CapitaLand|Capita<b>Land</b>]]<ref>x</ref>\n"
    assert registry.extract_operator(wikitext) == "CapitaLand"


@pytest.fixture
def hostile_index(monkeypatch):
    df = data_loader.load_default_index().copy()
    df.loc[df["rank"] == 1, ["name", "operator", "region"]] = [HOSTILE, HOSTILE, HOSTILE]
    monkeypatch.setattr(data_loader, "load_default_index", lambda: df)
    return df


def test_map_tooltip_data_is_html_escaped(hostile_index):
    at = AppTest.from_file(str(APP / "pages" / "4_National_Map.py"), default_timeout=120).run()
    assert not at.exception
    deck = at.get("deck_gl_json_chart")[0].proto
    # The tooltip template is HTML: it may only read the escaped copies of scraped fields.
    assert "{tip_name}" in deck.tooltip and "{tip_region}" in deck.tooltip
    assert "{name}" not in deck.tooltip and "{region}" not in deck.tooltip
    assert "&lt;img" in deck.json


def test_names_render_literally_in_markdown(hostile_index):
    at = AppTest.from_file(str(APP / "pages" / "3_Mall_Comparison.py"), default_timeout=120).run()
    assert not at.exception
    assert not any("<img" in m.value and "\\<img" not in m.value for m in at.markdown)
    assert any("\\*bold\\*" in m.value for m in at.markdown)
