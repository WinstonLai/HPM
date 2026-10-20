"""Small geo helpers: haversine distance and polygon centroids.

Kept dependency-free (no geopandas/shapely) so the whole pipeline only needs
plain pandas/numpy, per the "only Python, minimal footprint" brief.
"""
from __future__ import annotations

import numpy as np

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Vectorised haversine distance in metres. Args may be scalars or arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def polygon_centroid(rings: list) -> tuple[float, float] | None:
    """Approximate centroid (lat, lon) of a GeoJSON Polygon/MultiPolygon geometry
    coordinate structure, using the simple vertex-average of the outer ring(s).

    This is not an area-weighted centroid, but for compact, roughly-convex
    URA subzone shapes it is a good enough approximation for a POC-scale
    catchment analysis and avoids taking a shapely/geopandas dependency.
    """
    lons, lats = [], []

    def _walk(coords):
        # GeoJSON Polygon: [ [ [lon,lat], ... ] , ...rings ]
        # GeoJSON MultiPolygon: [ [ [ [lon,lat], ... ] , ...rings ], ...polygons ]
        if not coords:
            return
        first = coords[0]
        if isinstance(first[0], (int, float)):
            # coords is a single ring: list of [lon, lat]
            for lon, lat in coords:
                lons.append(lon)
                lats.append(lat)
        else:
            for sub in coords:
                _walk(sub)

    _walk(rings)
    if not lons:
        return None
    return float(np.mean(lats)), float(np.mean(lons))


def nearby_mask(mall_lat, mall_lon, lats: np.ndarray, lons: np.ndarray, radius_m: float) -> np.ndarray:
    """Boolean mask of which (lats, lons) points fall within radius_m of a mall."""
    dist = haversine_m(mall_lat, mall_lon, lats, lons)
    return dist <= radius_m


# Raw counts are heavy-tailed: one mall with 50 eateries stretches the scale so
# the typical mall (median 8) scores ~16. Capping at the 95th percentile keeps
# the top ~5% of malls tied at 100 but stops them squashing everyone else, and
# brings each category's *effective* weight (weight x spread) close to its
# nominal weight.
WINSOR_QUANTILE = 0.95


def min_max_normalize(series, cap_quantile: float | None = WINSOR_QUANTILE):
    """Min-max scale a pandas Series to 0-100, first capping values at
    `cap_quantile` (pass None for a plain min-max). The cap is ignored when it
    would not exceed the minimum (e.g. a mostly-zero series whose 95th
    percentile is still 0). Constant/empty series -> all zeros."""
    lo, hi = series.min(), series.max()
    if cap_quantile is not None:
        cap = series.quantile(cap_quantile)
        if cap > lo:
            hi = cap
            series = series.clip(upper=cap)
    if hi - lo < 1e-9:
        return series * 0
    return (series - lo) / (hi - lo) * 100
