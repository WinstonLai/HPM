"""Behaviour added in the UX pass: shared custom-weights indicator, shareable ranking filters,
alias search, stale-data warning and the Methodology contents links."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP / "lib"))

import data_loader  # noqa: E402
import weights  # noqa: E402

RANKING = str(APP / "pages" / "1_National_Ranking.py")
CUSTOM = {**weights.default_settings(), "exclude_proxies": True}


def run(page: str, **state) -> AppTest:
    at = AppTest.from_file(page, default_timeout=120)
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def test_custom_weights_status_and_reset_are_in_the_sidebar_of_every_page():
    for page in [APP / "Home.py", *sorted((APP / "pages").glob("[1345]_*.py")), APP / "pages" / "7_Regional_Priorities.py"]:
        at = run(str(page), custom_weights=CUSTOM)
        assert not at.exception, page.name
        assert any("Custom weights are active" in w.value for w in at.sidebar.warning), page.name
        assert at.sidebar.button[0].label == "Reset to defaults", page.name     # first thing in the sidebar


def test_no_custom_weights_means_no_indicator():
    at = run(str(APP / "Home.py"))
    assert not list(at.sidebar.warning)


def test_reset_button_clears_the_custom_weights():
    at = run(str(APP / "Home.py"), custom_weights=CUSTOM)
    at.sidebar.button[0].click().run()
    assert "custom_weights" not in at.session_state and not list(at.sidebar.warning)


def test_ranking_filters_load_from_the_url_and_ignore_invalid_values():
    at = AppTest.from_file(RANKING, default_timeout=120)
    at.query_params["region"] = ["West", "Atlantis"]
    at.query_params["tier"] = ["Platinum"]
    at.run()
    assert not at.exception
    assert at.session_state["f_regions"] == ["West"]                 # "Atlantis" is not a region
    assert at.session_state["f_tiers"] == ["Platinum"]
    assert at.query_params["region"] == ["West"]                     # the URL is rewritten to match
    shown = int(at.caption[0].value.split()[1])
    assert 0 < shown < 187


def test_ranking_filters_are_mirrored_to_the_url_and_can_be_cleared():
    at = run(RANKING)
    at.text_input(key="f_search").set_value("Tampines").run()
    assert at.query_params["q"] == ["Tampines"]
    at.sidebar.button[-1].click().run()                              # Clear filters
    assert at.session_state["f_search"] == "" and "q" not in at.query_params


def test_ranking_search_also_matches_aliases():
    aliases = data_loader.load_aliases()
    aliased = aliases[aliases != ""]
    assert not aliased.empty
    alias = aliased.iloc[0].split("; ")[0]
    at = run(RANKING, f_search=alias)
    assert not at.exception and int(at.caption[0].value.split()[1]) >= 1


@pytest.mark.parametrize("days,stale", [(10, False), (400, True)])
def test_stale_data_warning(monkeypatch, days, stale):
    monkeypatch.setattr(data_loader, "load_meta", lambda: {
        "raw_data": {"latest_fetch": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}})
    assert data_loader.data_age_days() == days
    at = run(str(APP / "Home.py"))
    assert any("last fetched" in w.value for w in at.warning) is stale


def test_data_age_is_none_without_provenance(monkeypatch):
    monkeypatch.setattr(data_loader, "load_meta", lambda: {})
    assert data_loader.data_age_days() is None


def test_methodology_contents_link_to_real_anchors():
    at = run(str(APP / "pages" / "6_Methodology.py"))
    assert not at.exception
    contents = next(m.value for m in at.markdown if m.value.startswith("**Contents:**"))
    for anchor in ("big-picture", "categories", "normalisation", "worked-example", "limitations", "robustness"):
        assert f"(#{anchor})" in contents
        assert any(h.proto.anchor == anchor for h in at.header), anchor
