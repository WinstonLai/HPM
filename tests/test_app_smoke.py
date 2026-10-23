"""Run every Streamlit page headlessly against the committed CSVs, so a page
that raises (or a shared-settings state that breaks all of them) fails CI."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app"
PAGES = [APP / "Home.py", *sorted((APP / "pages").glob("*.py"))]
SIMULATOR = APP / "pages" / "2_What_If_Simulator.py"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(str(page), default_timeout=120).run()
    assert not at.exception


def test_crossed_tier_cutoffs_are_pushed_apart_and_every_page_still_renders():
    at = AppTest.from_file(str(SIMULATOR), default_timeout=120).run()
    at.slider(key="tier_Platinum").set_value(40).run()
    at.slider(key="tier_Gold").set_value(60).run()
    assert not at.exception
    assert at.slider(key="tier_Platinum").value == 60      # dragged up with Gold
    assert at.slider(key="tier_Gold").value == 60
    saved = at.session_state["custom_weights"]
    for page in PAGES:
        other = AppTest.from_file(str(page), default_timeout=120)
        other.session_state["custom_weights"] = saved
        assert not other.run().exception, page.name


def test_unusable_saved_settings_reset_instead_of_crashing():
    at = AppTest.from_file(str(APP / "Home.py"), default_timeout=120)
    at.session_state["custom_weights"] = {"supply": {}, "demand": {}, "supply_block": 70,
                                          "exclude_proxies": False, "tiers": {"Platinum": 50}}  # missing cut-offs
    at.run()
    assert not at.exception
    assert "custom_weights" not in at.session_state
