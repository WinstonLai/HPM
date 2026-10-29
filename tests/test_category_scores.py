import numpy as np
import pandas as pd
import pytest

import build_category_scores as bcs


def malls_df(rows):
    return pd.DataFrame(rows, columns=["name", "lat", "lon"])


def points(coords, **extra):
    return pd.DataFrame({"lat": [c[0] for c in coords], "lon": [c[1] for c in coords], **extra})


# ~111m per 0.001 degrees of latitude
A = ("Alpha Mall", 1.3000, 103.8000)
B = ("Beta Plaza", 1.3015, 103.8000)       # ~167m north of A


def test_lenient_normalisation_collides_but_strict_does_not():
    assert bcs.normalize_name("Tampines Mall") == bcs.normalize_name("Tampines Plaza") == "tampines"
    assert bcs.normalize_name_strict("Tampines Mall") != bcs.normalize_name_strict("Tampines Plaza")


def test_address_text_matching_uses_whole_words():
    malls = malls_df([("West Mall", 1.3, 103.8), ("IMM", 1.3, 103.8), ("Square 2", 1.3, 103.8)])
    addresses = pd.Series([
        "1 Jurong West Street 52",                # contains the word "west" but is not West Mall
        "1 Bukit Batok West Mall 658713",
        "2 Jurong East Street 21 IMM Building",
        "238 Thomson Road Novena Square 238895",  # ...square238... must not become "square 2"
    ])
    assert bcs.count_by_address_text(malls, addresses).tolist() == [1, 1, 0]


def test_count_nearby_radius():
    malls = malls_df([A])
    pts = points([(1.3005, 103.8), (1.3030, 103.8)])          # ~55m and ~333m away
    assert bcs.count_nearby(malls, pts, 200).tolist() == [1]
    assert bcs.count_nearby(malls, pts, 500).tolist() == [2]


def test_exclusive_assigns_each_point_to_its_nearest_mall_only():
    malls = malls_df([A, B])
    pts = points([(1.3008, 103.8)])                            # ~89m from A, ~78m from B -> nearer B
    shared = bcs.count_nearby(malls, pts, 200)
    exclusive = bcs.count_nearby(malls, pts, 200, exclusive=True)
    assert shared.tolist() == [1, 1]                           # without it, both malls claim the point
    assert exclusive.tolist() == [0, 1]
    assert exclusive.sum() <= len(pts)


def test_name_match_is_bounded_in_distance():
    malls = malls_df([A])
    pts = points([(1.3000, 103.8), (1.3600, 103.8)], BUILDING=["Alpha Mall", "Alpha Mall"])   # second is ~6.6km away
    bcs.FAR_NAME_MATCHES.clear()
    assert bcs.count_nearby(malls, pts, 200, "BUILDING", label="t").tolist() == [1]
    assert bcs.FAR_NAME_MATCHES and bcs.FAR_NAME_MATCHES[0]["mall"] == "Alpha Mall"


def test_name_match_is_skipped_for_names_shared_by_several_malls():
    malls = malls_df([("Rivervale Plaza", 1.3000, 103.8), ("Rivervale Mall", 1.3050, 103.8)])
    pts = points([(1.3050, 103.8)], BUILDING=["Rivervale Mall"])
    assert bcs.ambiguous_name_keys(malls) == {"rivervale"}
    # Plaza must not inherit the Mall's eatery just because the lenient names collide.
    assert bcs.count_nearby(malls, pts, 100, "BUILDING").tolist() == [0, 1]


def test_untapped_demand_is_nan_without_residents_and_ranks_the_shortfall_highest(monkeypatch):
    malls = malls_df([A] * 6)
    amenities = np.array([10, 20, 40, 80, 160, 5])
    monkeypatch.setattr(bcs, "count_nearby", lambda *a, **k: amenities)
    pop = np.array([1000.0, 2000.0, 4000.0, 8000.0, 0.0, 16000.0])   # amenities ~ proportional to pop, except the last
    pts = [points([(1.3, 103.8)])]
    got, per_10k, gap = bcs.compute_untapped_demand(malls, pop, pts)
    assert np.isnan(gap[4]) and np.isnan(per_10k[4])                  # no residents -> n/a, not 0
    valid = gap.drop(4)
    assert valid.between(0, 100).all()
    assert valid.idxmax() == 5                                         # 5 amenities for 16,000 people: biggest shortfall
    assert gap[5] == 100


def test_category_f_groups_by_landlord_and_adds_partner_bonus():
    malls = pd.DataFrame({
        "name": ["a", "b", "c", "d", "e"],
        "operator": ["Big Group", "Big Group", "Big Group", "Unknown", "Solo"],
        "hpb_partner": [0, 0, 0, 1, 0],
    })
    f = bcs.compute_category_f(malls)
    assert f[0] == f[1] == f[2] == pytest.approx(80)       # largest portfolio: 100 * 0.8
    assert f[3] == pytest.approx(20)                       # unknown landlord, but a confirmed partner
    assert f[4] == 0                                       # a portfolio of one scores 0


def test_station_access_counts_each_station_once():
    malls = malls_df([A])
    exits = points([(1.3002, 103.8), (1.3003, 103.8), (1.3004, 103.8), (1.3100, 103.8)],
                   STATION_NA=["BIG INTERCHANGE", "BIG INTERCHANGE", "BIG INTERCHANGE", "FAR STATION"])
    out = bcs.station_access(malls, exits, radius_m=1200)
    assert out.loc[0, "mrt_count"] == 2                     # 3 exits of one station + a second station
    assert out.loc[0, "mrt_nearest_m"] < 50
    assert 1.0 < out.loc[0, "mrt_access_index"] < 2.0        # nearer station counts for more than the far one


def test_kernel_catchment_fades_linearly_to_zero():
    malls = malls_df([A])
    sub = pd.DataFrame({"lat": [1.3000, 1.3090, 1.3300], "lon": [103.8] * 3, "v": [100.0, 100.0, 100.0]})
    out = bcs.kernel_catchments(malls, sub, ["v"], radius_m=2000)
    # at the mall: 100; ~1000m away: ~50; ~3.3km away: 0
    assert out.loc[0, "v"] == pytest.approx(100 + 100 * (1 - 1000 / 2000), abs=2.0)


def test_dedupe_against_drops_known_venues_and_self_duplicates():
    official = points([(1.3000, 103.8)])
    osm = points([(1.30001, 103.8), (1.3100, 103.8), (1.31001, 103.8)])   # 1st = a listed gym; 2nd/3rd = same new gym
    kept = bcs.dedupe_against(osm, official, 40)
    assert len(kept) == 1 and kept.loc[0, "lat"] == pytest.approx(1.3100)


def test_existing_hpm_flag_matches_aliases_and_match_as(tmp_path, monkeypatch):
    (tmp_path / "existing_hpm.csv").write_text(
        "name,source,match_as\nSingpost Centre,t,SingPost\nStamford House,t,\nGhost Mall,t,\n")
    monkeypatch.setattr(bcs, "MANUAL_DIR", tmp_path)
    malls = pd.DataFrame({"name": ["SingPost", "Capitol Building", "Other"],
                          "aliases": ["", "Stamford House", ""]})
    assert bcs.flag_existing_hpm(malls).tolist() == [1, 1, 0]


def test_existing_hpm_flag_is_zero_without_a_list(tmp_path, monkeypatch):
    monkeypatch.setattr(bcs, "MANUAL_DIR", tmp_path)
    assert bcs.flag_existing_hpm(pd.DataFrame({"name": ["A"], "aliases": [""]})).tolist() == [0]


def test_untapped_demand_never_expects_more_amenities_from_fewer_residents(monkeypatch):
    malls = malls_df([A] * 6)
    # A commercial core (50 residents, 90 amenities) alongside residential malls: the raw fit slopes downwards.
    amenities = np.array([90, 60, 50, 30, 20, 10])
    pop = np.array([50.0, 5000.0, 20000.0, 60000.0, 120000.0, 200000.0])
    monkeypatch.setattr(bcs, "count_nearby", lambda *a, **k: amenities)
    _, _, gap = bcs.compute_untapped_demand(malls, pop, [points([(1.3, 103.8)])])
    assert np.isnan(gap[0])                       # <1,000 residents: n/a, not a "severe shortfall"
    assert gap[5] == gap.max()                    # fewest amenities for the most people: biggest shortfall


def test_address_text_matching_uses_aliases_without_double_counting():
    malls = pd.DataFrame({"name": ["SingPost", "Lot 1"], "aliases": ["SingPost Centre", ""]})
    addrs = pd.Series(["10 EUNOS ROAD 8 SINGPOST CENTRE", "SINGPOST AND SINGPOST CENTRE", "LOT 1 CHOA CHU KANG", "LOT ONE SHOPPERS MALL", "ELSEWHERE"])
    assert bcs.count_by_address_text(malls, addrs).tolist() == [2, 2]
