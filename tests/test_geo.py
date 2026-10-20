import numpy as np
import pandas as pd
import pytest

import geo


def test_haversine_one_degree_of_latitude():
    d = geo.haversine_m(1.0, 103.8, 2.0, 103.8)
    assert d == pytest.approx(111_195, rel=1e-3)


def test_haversine_zero_for_same_point_and_vectorised():
    assert geo.haversine_m(1.3, 103.8, 1.3, 103.8) == pytest.approx(0)
    d = geo.haversine_m(1.3, 103.8, np.array([1.3, 1.31]), np.array([103.8, 103.8]))
    assert d.shape == (2,) and d[0] == pytest.approx(0) and d[1] > 1000


def test_min_max_plain_scales_to_0_100():
    out = geo.min_max_normalize(pd.Series([0, 5, 10]), cap_quantile=None)
    assert out.tolist() == [0, 50, 100]


def test_min_max_cap_stops_one_outlier_squashing_the_rest():
    s = pd.Series(list(range(100)) + [10_000])       # one mall far above the rest
    plain = geo.min_max_normalize(s, cap_quantile=None)
    capped = geo.min_max_normalize(s, cap_quantile=0.95)
    assert plain.median() < 1                        # the outlier flattens everyone else to ~0
    assert capped.median() > 40                      # ... but not once it is capped
    assert capped.iloc[-1] == 100 and capped.min() == 0
    cap = s.quantile(0.95)
    assert (capped[s >= cap] == 100).all()           # everything at/above the cap ties at 100


def test_min_max_cap_ignored_when_it_would_not_exceed_the_minimum():
    s = pd.Series([0] * 98 + [1, 5])                 # 95th percentile is still 0
    assert geo.min_max_normalize(s).max() == 100     # falls back to the true max
    assert geo.min_max_normalize(s).iloc[-1] == 100


def test_min_max_constant_series_is_all_zero():
    assert geo.min_max_normalize(pd.Series([3, 3, 3])).tolist() == [0, 0, 0]


def test_polygon_centroid_vertex_average():
    ring = [[103.0, 1.0], [104.0, 1.0], [104.0, 2.0], [103.0, 2.0]]
    lat, lon = geo.polygon_centroid([ring])
    assert (lat, lon) == pytest.approx((1.5, 103.5))
    assert geo.polygon_centroid([]) is None
