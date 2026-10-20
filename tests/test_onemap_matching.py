import onemap


def cand(building, postal="123456"):
    return {"building": building, "postal_code": postal, "lat": 1.3, "lon": 103.8, "address": building}


def test_name_tokens_drops_noise_and_maps_number_words():
    assert onemap.name_tokens("The Seletar Mall, Singapore") == ["seletar", "mall"]
    assert onemap.name_tokens("Lot One") == ["lot", "1"]
    assert onemap.name_tokens("313@somerset") == ["313", "somerset"]


def test_exact_match_beats_everything():
    assert onemap.match_score("Jurong Point", cand("JURONG POINT")) == 3
    assert onemap.match_score("Lot One", cand("LOT 1")) == 3


def test_tenant_inside_the_mall_is_an_acceptable_match():
    assert onemap.match_score("Suntec City", cand("GOLDEN VILLAGE (GV SUNTEC CITY)")) == 2


def test_wrong_building_is_rejected():
    # The real failures that motivated validation: OneMap ranked these first.
    assert onemap.match_score("Jurong Point", cand("FAMILY POINT CLINIC AND SURGERY TAMAN JURONG SHOPPING CENTRE")) == 0
    assert onemap.match_score("White Sands", cand("WHITE SANDS PRIMARY SCHOOL")) == 0
    assert onemap.match_score("NEX", cand("NEXUS INTERNATIONAL SCHOOL")) == 0
    assert onemap.match_score("Tangs", cand("CC TANG DENTAL SURGERY PTE LTD VISTA POINT")) == 0


def test_a_qualifier_after_the_mall_name_is_fine_unless_it_names_an_institution():
    for building in ("GREAT WORLD CITY", "ALEXANDRA RETAIL CENTRE (ARC)", "NORTHSHORE PLAZA I",
                     "HEARTLAND MALL-KOVAN", "ZHUJIAO CENTRE (TEKKA MARKET)", "HARBOURFRONT CENTRE CHECKPOINT"):
        name = {"GREAT WORLD CITY": "Great World", "ALEXANDRA RETAIL CENTRE (ARC)": "Alexandra Retail Centre",
                "NORTHSHORE PLAZA I": "Northshore Plaza", "HEARTLAND MALL-KOVAN": "Heartland Mall",
                "ZHUJIAO CENTRE (TEKKA MARKET)": "Zhujiao Centre",
                "HARBOURFRONT CENTRE CHECKPOINT": "HarbourFront Centre"}[building]
        assert onemap.match_score(name, cand(building)) >= 2, building
    assert onemap.match_score("White Sands", cand("WHITE SANDS PRIMARY SCHOOL")) == 0
    assert onemap.match_score("Ang Mo Kio Town Centre", cand("ANG MO KIO TOWN COUNCIL (SERVICE CENTRE)")) == 0
    assert onemap.match_score("Tampines Mall", cand("TAMPINES MALL CARPARK")) == 0


def test_sibling_malls_with_a_shared_first_word_are_not_confused():
    assert onemap.match_score("Rivervale Plaza", cand("RIVERVALE MALL")) == 0
    assert onemap.match_score("Tampines 1", cand("TAMPINES PLAZA 1")) == 0


def test_loose_tier_only_ignores_trailing_generic_words():
    assert onemap.match_score("Cheng San Centre", cand("CHENG SAN SHOPPING CENTRE")) >= 1
    assert onemap.match_score("Hougang Town Centre", cand("ALJUNIED-HOUGANG TOWN COUNCIL (COLLECTION SERVICE)")) == 0


def test_best_candidate_skips_a_better_ranked_wrong_hit():
    candidates = [cand("FAMILY POINT CLINIC TAMAN JURONG", None), cand("GOLDEN VILLAGE (GV JURONG POINT)", None),
                  cand("JURONG POINT", "648886")]
    assert onemap.best_candidate("Jurong Point", candidates)["postal_code"] == "648886"


def test_best_candidate_returns_none_when_nothing_matches():
    assert onemap.best_candidate("Orchard Point", [cand("JUSTCO PLACE")]) is None


def test_number_variants_try_the_other_spelling():
    assert onemap._number_variants("Lot 1") == ["Lot one"]
    assert onemap._number_variants("Lot One") == ["Lot 1"]
    assert onemap._number_variants("Funan") == []
