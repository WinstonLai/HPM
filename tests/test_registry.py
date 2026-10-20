import pandas as pd
import pytest

import build_mall_registry as reg


def test_clean_name_strips_wikipedia_disambiguation():
    assert reg.clean_name("Funan, Singapore") == "Funan"
    assert reg.clean_name("IMM (Singapore)") == "IMM"
    assert reg.clean_name("Bugis+") == "Bugis+"


@pytest.mark.parametrize("a,b", [("Lot One", "Lot 1"), ("The Seletar Mall", "Seletar Mall"),
                                 ("Funan, Singapore", "Funan"), ("Nex, Singapore", "NEX")])
def test_dedupe_key_treats_naming_variants_as_one_mall(a, b):
    assert reg.dedupe_key(a) == reg.dedupe_key(b)


@pytest.mark.parametrize("a,b", [("Rivervale Plaza", "Rivervale Mall"), ("Tampines 1", "Tampines Mall")])
def test_dedupe_key_keeps_different_malls_apart(a, b):
    assert reg.dedupe_key(a) != reg.dedupe_key(b)


def test_extract_operator_prefers_owner_over_developer():
    wikitext = "| developer = [[CapitaLand|Developer Co]]\n| owner = [[Frasers Property]]\n| management = Someone"
    assert reg.extract_operator(wikitext) == "Frasers Property"
    assert reg.extract_operator("| developer = Builder Pte Ltd\n| management = Mgr") == "Mgr"
    assert reg.extract_operator("| developer = Builder Pte Ltd") == "Builder Pte Ltd"
    assert reg.extract_operator("nothing useful") == "Unknown"


def test_extract_operator_strips_markup():
    assert reg.extract_operator("| owner = [[A|Alpha]]<ref>cite</ref><br>second") == "Alpha"


def test_clean_operator_applies_aliases_and_drops_non_landlords():
    aliases = {"capitamall trust": "CapitaLand", "golden village": ""}
    assert reg.clean_operator("CapitaMall Trust", aliases) == "CapitaLand"
    assert reg.clean_operator("Golden Village", aliases) == "Unknown"        # blank alias = not a landlord
    assert reg.clean_operator("Eng Wah Organisation (former)", aliases) == "Unknown"
    assert reg.clean_operator("Far East Organization", aliases) == "Far East Organization"
    assert reg.clean_operator("", aliases) == "Unknown"


def mall(name, lat, lon, postal, canonical=""):
    return {"name": name, "lat": lat, "lon": lon, "postal_code": postal, "canonical_title": canonical,
            "operator": "Unknown", "region": "Unknown", "address": f"{name} addr"}


def test_merge_duplicates_same_building_or_near_with_shared_word():
    df = pd.DataFrame([
        mall("Raffles City", 1.2939, 103.8531, "179103"),
        mall("Raffles City Shopping Centre", 1.2939, 103.8531, "179103"),     # same postal -> merge
        mall("Capitol Piazza", 1.2934, 103.8515, None),
        mall("Capitol Singapore", 1.29345, 103.85152, None),                   # ~1m, shared word, no postal -> merge
        mall("Bugis Junction", 1.2999, 103.8554, "188021"),
        mall("Bugis+", 1.2996, 103.8542, "188067"),                            # different postal -> never merged
        mall("Orchard Central", 1.30085, 103.84540, "238896"),
        mall("Orchard Gateway", 1.30110, 103.84560, None),                     # 44m, but only "orchard" in common
    ])
    merged, qa = reg.merge_duplicates(df)
    assert sorted(merged["name"]) == ["Bugis Junction", "Bugis+", "Capitol Piazza", "Orchard Central",
                                      "Orchard Gateway", "Raffles City"]
    assert len(qa) == 2
    assert merged.set_index("name").loc["Raffles City", "aliases"] == "Raffles City Shopping Centre"


def test_merge_duplicates_keeps_first_and_fills_missing_fields():
    a, b = mall("Alpha Mall", 1.30, 103.80, "111111"), mall("Alpha Plaza", 1.30, 103.80, "111111")
    b["operator"] = "Far East Organization"
    merged, _ = reg.merge_duplicates(pd.DataFrame([a, b]))
    assert merged.iloc[0]["name"] == "Alpha Mall" and merged.iloc[0]["operator"] == "Far East Organization"


@pytest.mark.parametrize("name,source,expected", [
    ("Funan", "regional", "Shopping mall"),
    ("Yew Tee Square", "estate", "Neighbourhood centre"),
    ("Bishan Town Centre", "estate", "Area / precinct"),
    ("Tekka Hawker Centre", "category", "Market / hawker centre"),
    ("Terminal 3", "existing_hpm", "Shopping mall"),
])
def test_classify_type_rules(name, source, expected):
    assert reg.classify_type(name, source, {}) == expected


def test_manual_type_beats_rules_and_hpm_status_beats_keywords():
    manual = {reg.dedupe_key("Potong Pasir"): "Area / precinct"}
    assert reg.classify_type("Potong Pasir", "category", manual) == "Area / precinct"
    assert reg.classify_type("Hougang Market Square", "existing_hpm", {}) == "Shopping mall"


def test_slugify_is_stable():
    assert reg.slugify("Funan, Singapore") == "funan"
    assert reg.slugify("Bugis+") == "bugis"


def test_merge_duplicates_preserves_existing_aliases_and_partner_flag():
    a = {**mall("Alpha Mall", 1.30, 103.80, "111111"), "aliases": "Old Alias", "hpb_partner": 0}
    b = {**mall("Alpha Plaza", 1.30, 103.80, "111111"), "aliases": "", "hpb_partner": 1}
    c = {**mall("Lonely Mall", 1.40, 103.90, "222222"), "aliases": "Keep Me", "hpb_partner": 0}
    merged, _ = reg.merge_duplicates(pd.DataFrame([a, b, c]))
    rows = merged.set_index("name")
    assert rows.loc["Alpha Mall", "aliases"] == "Old Alias; Alpha Plaza"
    assert rows.loc["Alpha Mall", "hpb_partner"] == 1
    assert rows.loc["Lonely Mall", "aliases"] == "Keep Me"          # untouched malls keep their aliases
