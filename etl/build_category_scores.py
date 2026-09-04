"""Join every raw amenity/context dataset to the mall registry and compute
one normalised 0-100 score per HPM category (A-G) per mall, plus the raw
counts each score is built from (kept for transparency in the dashboard).

Matching strategy
------------------
Datasets that carry a clean building-name field (e.g. HPB's Healthier
Eateries / CHAS Clinics `BUILDING_NAME`) are matched to a mall first by
normalised building-name equality, then everything (matched or not) is
additionally checked by straight-line distance so amenities that are on-site
but named slightly differently (e.g. "ABC Mall Level 2") still count.

Radii (deliberately generous for a POC without exact building footprints):
  ON_SITE_RADIUS_M  - dining / fitness / healthcare / bicycle racks "at" a mall
  NEARBY_RADIUS_M   - community clubs / parks "near" a mall
  CATCHMENT_RADIUS_M - population / MRT / bus for demand-side accessibility

Every raw count is then min-max normalised to 0-100 across the mall
population. This is documented as a simplification: the charter's own
worked example normalises by dividing by each mall's *total* tenant count
(e.g. "% of F&B outlets in HDP"), which requires a full per-mall tenant
directory that is not publicly available. Min-max scaling still fixes the
core bias the charter is warning about (a big mall's raw count no longer
mechanically wins), just not via the exact same formula.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datagovsg import RAW_DIR, feature_attributes, feature_point, load_geojson_features  # noqa: E402
from geo import haversine_m, min_max_normalize, polygon_centroid  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

ON_SITE_RADIUS_M = 200
NEARBY_RADIUS_M = 500
CATCHMENT_RADIUS_M = 1200
BUS_RADIUS_M = 400

MALL_SUFFIX_RE = re.compile(
    r"\b(shopping (mall|centre|center)|mall|centre|center|plaza|building|mrt|singapore)\b",
    re.IGNORECASE,
)
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    name = (name or "").lower()
    name = MALL_SUFFIX_RE.sub("", name)
    name = NON_ALNUM_RE.sub("", name)
    return name


def normalize_name_strict(name: str) -> str:
    """Like normalize_name but keeps generic suffix words ("mall", "plaza",
    "west", ...) instead of stripping them, and keeps a single space between
    tokens instead of fusing them together. Used only for free-text
    substring matching, where two problems otherwise appear:
      1. stripping to a bare word like "West Mall" -> "west" would match
         almost any address in western Singapore (Jurong West, Sengkang
         West, Admiralty Road West, ...);
      2. fusing all tokens together (no separator) can coincidentally glue
         an unrelated block/unit number onto a preceding word and form a
         false match, e.g. "Novena Square" + "238 Thomson Road" fuses into
         "...square238..." which contains "square2" (a false hit for the
         mall "Square 2"). Keeping single spaces and padding both sides
         before matching turns that into a proper whole-word check.
    Equality-based building-name matching doesn't have either problem and
    still uses the lenient, fully-fused normalize_name."""
    name = (name or "").lower()
    return NON_ALNUM_RE.sub(" ", name).strip()


def count_by_address_text(malls: pd.DataFrame, addresses: pd.Series) -> np.ndarray:
    """Count matches for datasets published as a plain CSV with a free-text
    address column and no coordinates (e.g. HPB's Healthier Dining Partners,
    HSA's Licensed Pharmacies) -- normalise both sides and word-boundary
    substring-match the mall's full name inside the outlet address. Skipped
    for very short mall names (<4 normalised chars) to avoid spurious
    matches."""
    norm_addresses = addresses.fillna("").map(lambda a: f" {normalize_name_strict(a)} ").to_numpy()
    counts = np.zeros(len(malls), dtype=int)
    for i, mall_name in enumerate(malls["name"]):
        key = normalize_name_strict(mall_name)
        if len(key) < 4:
            continue
        padded_key = f" {key} "
        counts[i] = sum(1 for addr in norm_addresses if padded_key in addr)
    return counts


def load_csv_addresses(filename: str, address_cols: str | list[str]) -> pd.Series:
    """Return a Series of free-text addresses from a CSV. `address_cols` is
    either a single already-combined address column, or a list of columns
    (e.g. NEA's supermarket licences: building_name/block_house_num/
    street_name are separate fields) to concatenate into one address string."""
    path = RAW_DIR / filename
    if not path.exists():
        print(f"  [warn] missing raw file {filename}, skipping this source")
        return pd.Series(dtype=str)
    df = pd.read_csv(path)
    if isinstance(address_cols, str):
        return df[address_cols]
    return df[address_cols].fillna("").astype(str).agg(" ".join, axis=1)


def load_points(filename: str) -> pd.DataFrame:
    """Load a GeoJSON dataset's Point features into a flat DataFrame with
    at least lat/lon columns, plus whatever attributes were present."""
    path = RAW_DIR / filename
    if not path.exists():
        print(f"  [warn] missing raw file {filename}, skipping this source")
        return pd.DataFrame(columns=["lat", "lon"])
    rows = []
    for feat in load_geojson_features(path):
        pt = feature_point(feat)
        if pt is None:
            continue
        lat, lon = pt
        attrs = feature_attributes(feat)
        rows.append({**attrs, "lat": lat, "lon": lon})
    return pd.DataFrame(rows)


def count_nearby(malls: pd.DataFrame, points: pd.DataFrame, radius_m: float,
                  building_col: str | None = None) -> np.ndarray:
    """For each mall, count how many `points` are within radius_m OR share a
    normalised building name with the mall (when building_col is given)."""
    counts = np.zeros(len(malls), dtype=int)
    if points.empty:
        return counts

    plat = points["lat"].to_numpy(dtype=float)
    plon = points["lon"].to_numpy(dtype=float)

    point_names = None
    if building_col and building_col in points.columns:
        point_names = points[building_col].fillna("").map(normalize_name).to_numpy()

    for i, mall in enumerate(malls.itertuples()):
        dist = haversine_m(mall.lat, mall.lon, plat, plon)
        mask = dist <= radius_m
        if point_names is not None:
            mall_norm = normalize_name(mall.name)
            if mall_norm:
                mask = mask | (point_names == mall_norm)
        counts[i] = int(mask.sum())
    return counts


def load_subzone_population() -> pd.DataFrame:
    """Parse the SingStat resident-population CSV (subzone rows nested under
    '<Planning Area> - Total' rows) into one row per subzone with total and
    senior (65+) population."""
    path = RAW_DIR / "resident_population_2020.csv"
    if not path.exists():
        print("  [warn] missing resident_population_2020.csv")
        return pd.DataFrame(columns=["subzone", "planning_area", "total_pop", "senior_pop"])

    df = pd.read_csv(path)
    elderly_cols = [c for c in df.columns if any(
        c.startswith(f"Total_{age}") for age in
        ["65_69", "70_74", "75_79", "80_84", "85_89", "90andOver"]
    )]

    rows = []
    current_area = None
    for _, row in df.iterrows():
        label = str(row["Number"]).strip()
        if label.lower() == "total":
            continue
        if label.endswith("- Total"):
            current_area = label[: -len("- Total")].strip()
            continue
        total_pop = pd.to_numeric(row.get("Total_Total"), errors="coerce")
        senior_pop = pd.to_numeric(row[elderly_cols], errors="coerce").sum() if elderly_cols else 0
        if pd.isna(total_pop):
            continue
        rows.append({
            "subzone": label,
            "planning_area": current_area,
            "total_pop": total_pop,
            "senior_pop": senior_pop,
        })
    return pd.DataFrame(rows)


def load_subzone_centroids() -> pd.DataFrame:
    path = RAW_DIR / "subzone_boundary.geojson"
    if not path.exists():
        print("  [warn] missing subzone_boundary.geojson")
        return pd.DataFrame(columns=["subzone", "region", "lat", "lon"])
    rows = []
    for feat in load_geojson_features(path):
        props = feat.get("properties", {}) or {}
        name = props.get("SUBZONE_N")
        geom = feat.get("geometry") or {}
        centroid = polygon_centroid(geom.get("coordinates") or [])
        if name and centroid:
            region_n = (props.get("REGION_N") or "").title().replace(" Region", "")
            rows.append({"subzone": name, "region": region_n or "Unknown",
                         "lat": centroid[0], "lon": centroid[1]})
    return pd.DataFrame(rows)


def assign_region(malls: pd.DataFrame, centroids: pd.DataFrame) -> pd.Series:
    """Authoritative region for every mall: the URA region of its nearest
    subzone centroid. This overrides whatever region a mall's Wikipedia
    source gave it (or "Unknown" for the ~140 malls added from the category/
    commercial-sites sources that don't carry a region label at scrape
    time), so every mall in the registry ends up with a consistent,
    data-driven region regardless of which source it came from."""
    if centroids.empty:
        return pd.Series(["Unknown"] * len(malls), index=malls.index)

    clat = centroids["lat"].to_numpy(dtype=float)
    clon = centroids["lon"].to_numpy(dtype=float)
    cregion = centroids["region"].to_numpy()

    regions = []
    for mall in malls.itertuples():
        dist = haversine_m(mall.lat, mall.lon, clat, clon)
        regions.append(cregion[int(np.argmin(dist))])
    return pd.Series(regions, index=malls.index)


def compute_population_catchment(malls: pd.DataFrame, centroids: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    pop = load_subzone_population()
    if pop.empty or centroids.empty:
        z = np.zeros(len(malls))
        return z, z

    pop["subzone_key"] = pop["subzone"].str.upper().str.strip()
    centroids["subzone_key"] = centroids["subzone"].str.upper().str.strip()
    merged = pop.merge(centroids, on="subzone_key", how="inner", suffixes=("", "_geo"))

    slat = merged["lat"].to_numpy(dtype=float)
    slon = merged["lon"].to_numpy(dtype=float)
    stotal = merged["total_pop"].to_numpy(dtype=float)
    ssenior = merged["senior_pop"].to_numpy(dtype=float)

    total_catchment = np.zeros(len(malls))
    senior_catchment = np.zeros(len(malls))
    for i, mall in enumerate(malls.itertuples()):
        dist = haversine_m(mall.lat, mall.lon, slat, slon)
        mask = dist <= CATCHMENT_RADIUS_M
        total_catchment[i] = stotal[mask].sum()
        senior_catchment[i] = ssenior[mask].sum()
    return total_catchment, senior_catchment


def compute_category_f(malls: pd.DataFrame) -> pd.Series:
    """Partnership Readiness proxy: portfolio scale of the mall's operator
    (a larger chain is more likely to have centralised CSR/health-programme
    capacity) plus a bonus for the one publicly confirmed HPM partnership
    named on HPB's own website (Downtown East)."""
    chain_size = malls.groupby("operator")["operator"].transform("count")
    chain_size = chain_size.where(malls["operator"] != "Unknown", 1)
    chain_score = min_max_normalize(chain_size)

    confirmed_partners = {normalize_name("Downtown East")}
    bonus = malls["name"].map(normalize_name).isin(confirmed_partners).astype(float) * 20

    return (chain_score * 0.8 + bonus).clip(upper=100)


def build_category_scores() -> pd.DataFrame:
    malls_path = PROCESSED_DIR / "malls.csv"
    malls = pd.read_csv(malls_path)
    print(f"Loaded {len(malls)} malls from {malls_path}")

    out = malls[["mall_id", "name", "region", "operator", "lat", "lon"]].copy()

    print("Assigning authoritative region (nearest URA subzone) ...")
    subzone_centroids = load_subzone_centroids()
    out["region"] = assign_region(malls, subzone_centroids)

    print("Category A - Healthy Dining Ecosystem (incl. supermarkets) ...")
    dining = load_points("healthier_eateries.geojson")
    dining_partners = load_csv_addresses("healthier_dining_fnb_partners.csv", "Outlet_Address")
    # NEA's licence list has no single address field -- build one from its
    # separate building_name/block_house_num/street_name columns.
    supermarkets = load_csv_addresses(
        "supermarket_licences.csv", ["building_name", "block_house_num", "street_name"]
    )
    out["A_supermarket_count"] = count_by_address_text(malls, supermarkets)
    out["A_dining_count"] = (
        count_nearby(malls, dining, ON_SITE_RADIUS_M, "ADDRESSBUILDINGNAME")
        + count_by_address_text(malls, dining_partners)
        + out["A_supermarket_count"]
    )
    out["A_dining_score"] = min_max_normalize(out["A_dining_count"])

    print("Category B - Physical Activity Ecosystem ...")
    fitness = pd.concat([
        load_points("gyms_at_sg.geojson"),
        load_points("sportsg_sport_facilities.geojson"),
    ], ignore_index=True)
    out["B_fitness_count"] = count_nearby(malls, fitness, ON_SITE_RADIUS_M)
    out["B_fitness_score"] = min_max_normalize(out["B_fitness_count"])

    print("Category C - H365 & HPB Engagement (community-club proxy) ...")
    community = load_points("community_clubs.geojson")
    out["C_engagement_count"] = count_nearby(malls, community, NEARBY_RADIUS_M)
    out["C_engagement_score"] = min_max_normalize(out["C_engagement_count"])

    print("Category D - Healthcare Ecosystem ...")
    healthcare = load_points("chas_clinics.geojson")
    pharmacies = load_csv_addresses("licensed_pharmacies.csv", "PharmacyAddress")
    out["D_healthcare_count"] = (
        count_nearby(malls, healthcare, ON_SITE_RADIUS_M, "BUILDING_NAME")
        + count_by_address_text(malls, pharmacies)
    )
    out["D_healthcare_score"] = min_max_normalize(out["D_healthcare_count"])

    print("Category E - Healthy Infrastructure (parks + bicycle racks) ...")
    infra = pd.concat([
        load_points("parks_at_sg.geojson"),
        load_points("park_facilities.geojson"),
    ], ignore_index=True)
    bike_racks = load_points("bicycle_racks.geojson")
    out["E_bike_rack_count"] = count_nearby(malls, bike_racks, ON_SITE_RADIUS_M)
    out["E_infra_count"] = count_nearby(malls, infra, NEARBY_RADIUS_M) + out["E_bike_rack_count"]
    out["E_infra_score"] = min_max_normalize(out["E_infra_count"])

    print("Category F - Landlord & Partnership Readiness (operator proxy) ...")
    out["F_partnership_score"] = compute_category_f(malls)

    print("Demand side - population catchment, accessibility ...")
    total_pop, senior_pop = compute_population_catchment(malls, subzone_centroids)
    out["pop_catchment"] = total_pop
    out["senior_pop_catchment"] = senior_pop
    out["reach_population_score"] = (
        min_max_normalize(pd.Series(total_pop)) * 0.7
        + min_max_normalize(pd.Series(senior_pop)) * 0.3
    )

    mrt = load_points("mrt_station_exits.geojson")
    bus = load_points("bus_stops.geojson")
    out["mrt_count"] = count_nearby(malls, mrt, CATCHMENT_RADIUS_M)
    out["bus_count"] = count_nearby(malls, bus, BUS_RADIUS_M)
    out["accessibility_score"] = (
        min_max_normalize(out["mrt_count"]) * 0.5 + min_max_normalize(out["bus_count"]) * 0.5
    )

    # Engagement Gap: charter defines "untapped demand" as low existing H365/
    # HPB engagement despite catchment potential -- proxied as the inverse of
    # Category C's own score.
    out["engagement_gap_score"] = 100 - out["C_engagement_score"]

    out_path = PROCESSED_DIR / "category_scores.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {len(out)} malls x category scores to {out_path}")
    return out


if __name__ == "__main__":
    build_category_scores()
