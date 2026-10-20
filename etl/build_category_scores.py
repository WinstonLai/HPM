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
directory that is not publicly available. Min-max scaling is only a linear
rescale of the raw count: it makes categories comparable so they can be
weighted and summed, but it does NOT remove the size bias the charter is
warning about (within a category the ranking equals the raw-count ranking).
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
from onemap import name_tokens  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

ON_SITE_RADIUS_M = 200
NEARBY_RADIUS_M = 500
CATCHMENT_RADIUS_M = 1200
BUS_RADIUS_M = 400
# Reach & Population weights nearby people by distance instead of a hard
# circle: a subzone's people count in proportion to 1 - distance/this radius.
REACH_KERNEL_RADIUS_M = 2000
# OSM fitness venues within this distance of a Gyms@SG / SportSG point are
# treated as the same venue.
OSM_DEDUPE_M = 40
MANUAL_DIR = Path(__file__).resolve().parent.parent / "data" / "manual"

# NParks' Park Facilities file lists every piece of park furniture (mostly
# carparks, noticeboards, access points, toilets, ...). Only these classes
# count towards Healthy Infrastructure: the charter's children's playgrounds
# and fitness corners, water refill points (DRINKING FOUNTAIN) and wellness
# facilities (FOOT RELAX).
PARK_FACILITY_CLASSES = {"PLAYGROUND", "FITNESS AREA", "DRINKING FOUNTAIN", "FOOT RELAX"}


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
    substring-match the mall's full name inside the outlet address. The
    padding-based word-boundary check (not a length cutoff) is what guards
    against spurious matches, so short names like "IMM" or "Duo" are matched
    the same as any other -- see normalize_name_strict's docstring."""
    norm_addresses = addresses.fillna("").map(lambda a: f" {normalize_name_strict(a)} ").to_numpy()
    counts = np.zeros(len(malls), dtype=int)
    for i, mall_name in enumerate(malls["name"]):
        key = normalize_name_strict(mall_name)
        if not key:
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


POSTAL_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _brand_key(name) -> str:
    return NON_ALNUM_RE.sub("", str(name).lower())


def load_deduped_partner_addresses(eateries: pd.DataFrame) -> pd.Series:
    """Addresses of Healthier Dining Partners outlets, minus outlets already
    counted as Healthier Eateries.

    The two HPB datasets describe largely the same outlets (500+ shared
    postal codes), so summing them double-counts. An outlet is treated as the
    same one when postal code and brand match (eatery NAME is "<Brand> -
    <location>"; partners have a Brand_Name column). The partners file also
    repeats some rows verbatim (e.g. one brand spelled "Wingstop" and
    "WINGSTOP" at the same address), which are collapsed too. Outlets whose
    address has no parseable postal code can't be cross-matched against the
    eateries and are kept."""
    path = RAW_DIR / "healthier_dining_fnb_partners.csv"
    if not path.exists():
        print("  [warn] missing raw file healthier_dining_fnb_partners.csv, skipping this source")
        return pd.Series(dtype=str)
    partners = pd.read_csv(path)
    partners["_pc"] = partners["Outlet_Address"].fillna("").str.extract(POSTAL_RE)[0]
    partners["_brand"] = partners["Brand_Name"].map(_brand_key)

    if "ADDRESSPOSTALCODE" in eateries.columns and "NAME" in eateries.columns:
        eatery_pc = eateries["ADDRESSPOSTALCODE"].astype(str).str.extract(POSTAL_RE)[0]
        eatery_brand = eateries["NAME"].astype(str).str.split(r"\s+-\s+").str[0].map(_brand_key)
        eatery_keys = set(zip(eatery_pc, eatery_brand))
        already_counted = [
            (pc, b) in eatery_keys if isinstance(pc, str) else False
            for pc, b in zip(partners["_pc"], partners["_brand"])
        ]
        partners = partners[~pd.Series(already_counted, index=partners.index)]

    partners = partners.assign(_addr=partners["Outlet_Address"].fillna("").map(normalize_name_strict))
    partners = partners.drop_duplicates(subset=["_addr", "_brand"])
    return partners["Outlet_Address"]


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


def ambiguous_name_keys(malls: pd.DataFrame) -> set[str]:
    """Lenient name keys shared by more than one mall ("Rivervale Plaza" and
    "Rivervale Mall" both reduce to "rivervale"). Name equality can't tell
    those malls apart, so it is not used for them -- only distance is."""
    keys = malls["name"].map(normalize_name)
    return set(keys[keys.duplicated(keep=False)]) - {""}


# Name-equality matches are accepted only this close to the mall. The
# lenient key reduces e.g. "Tampines Mall"/"Tampines Plaza"/"Tampines Centre"
# to one word, and a geocode error can put a mall kilometres from its own
# building; without a bound either case silently pulls in far-away amenities.
NAME_MATCH_MAX_M = 500

# Name matches rejected for being too far away. A mall that shows up here
# usually has a bad geocode, so this doubles as a registry QA signal.
FAR_NAME_MATCHES: list[dict] = []


def count_nearby(malls: pd.DataFrame, points: pd.DataFrame, radius_m: float,
                  building_col: str | None = None, label: str = "",
                  exclusive: bool = False) -> np.ndarray:
    """For each mall, count how many `points` are within radius_m OR share a
    normalised building name with the mall (when building_col is given) AND
    lie within NAME_MATCH_MAX_M of it. Name equality is skipped for names
    shared by several malls (see ambiguous_name_keys).

    exclusive=True assigns every point to its NEAREST mall only (a point still
    needs to be within radius_m of that mall). Use it for "on-site" amenities
    (dining, gyms, clinics, bike racks): otherwise one eatery between two
    adjacent malls (Bugis Junction / Bugis+, the Orchard cluster) is counted
    for both. A mall's own building-name match always counts for that mall."""
    counts = np.zeros(len(malls), dtype=int)
    if points.empty:
        return counts

    plat = points["lat"].to_numpy(dtype=float)
    plon = points["lon"].to_numpy(dtype=float)
    nearest = None
    if exclusive:
        nearest = np.vstack([haversine_m(m.lat, m.lon, plat, plon) for m in malls.itertuples()]).argmin(axis=0)

    point_names = None
    if building_col and building_col in points.columns:
        point_names = points[building_col].fillna("").map(normalize_name).to_numpy()
    ambiguous = ambiguous_name_keys(malls) if point_names is not None else set()

    for i, mall in enumerate(malls.itertuples()):
        dist = haversine_m(mall.lat, mall.lon, plat, plon)
        mask = dist <= radius_m
        if nearest is not None:
            mask &= nearest == i
        if point_names is not None:
            mall_norm = normalize_name(mall.name)
            if mall_norm and mall_norm not in ambiguous:
                name_hit = point_names == mall_norm
                mask = mask | (name_hit & (dist <= NAME_MATCH_MAX_M))
                far = name_hit & (dist > NAME_MATCH_MAX_M)
                if far.any():
                    FAR_NAME_MATCHES.append({
                        "dataset": label, "mall": mall.name, "n_far_name_matches": int(far.sum()),
                        "max_distance_m": int(dist[far].max()),
                    })
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
        return pd.DataFrame(columns=["subzone", "region", "planning_area", "area", "lat", "lon"])
    rows = []
    for feat in load_geojson_features(path):
        props = feat.get("properties", {}) or {}
        name = props.get("SUBZONE_N")
        geom = feat.get("geometry") or {}
        centroid = polygon_centroid(geom.get("coordinates") or [])
        if name and centroid:
            region_n = (props.get("REGION_N") or "").title().replace(" Region", "")
            rows.append({"subzone": name, "region": region_n or "Unknown",
                         "planning_area": (props.get("PLN_AREA_N") or "").strip().upper(),
                         "area": float(props.get("SHAPE.AREA") or 0.0),
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


def assign_planning_area(malls: pd.DataFrame, centroids: pd.DataFrame) -> pd.Series:
    """URA planning area (upper case) of each mall's nearest subzone centroid."""
    if centroids.empty:
        return pd.Series([""] * len(malls), index=malls.index)
    clat = centroids["lat"].to_numpy(dtype=float)
    clon = centroids["lon"].to_numpy(dtype=float)
    pa = centroids["planning_area"].to_numpy()
    return pd.Series([pa[int(np.argmin(haversine_m(m.lat, m.lon, clat, clon)))] for m in malls.itertuples()],
                     index=malls.index)


def load_workers_by_planning_area() -> pd.Series:
    """Employed residents by planning area of WORKPLACE (Census 2020), indexed
    by upper-case planning area. Residents only: foreign workers and visitors
    are not included, so this understates daytime population, most of all for
    the CBD and the airport."""
    path = RAW_DIR / "workers_by_workplace_pa_2020.csv"
    if not path.exists():
        print("  [warn] missing workers_by_workplace_pa_2020.csv -- worker component will be 0")
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    df["pa"] = df["Number"].astype(str).str.strip().str.upper()
    df = df[df["pa"] != "TOTAL"]
    return pd.to_numeric(df.set_index("pa")["Total_Total"], errors="coerce").dropna()


def build_subzone_table(centroids: pd.DataFrame) -> pd.DataFrame:
    """One row per URA subzone with residents, seniors and workers. Residents
    come from the subzone-level census; workers are only published per
    planning area, so each planning area's workers are spread over its
    subzones in proportion to polygon area -- an approximation (commercial
    subzones are small, so they are under-weighted within their area)."""
    sub = centroids.copy()
    sub["key"] = sub["subzone"].str.upper().str.strip()
    pop = load_subzone_population()
    if not pop.empty:
        pop["key"] = pop["subzone"].str.upper().str.strip()
        sub = sub.merge(pop[["key", "total_pop", "senior_pop"]], on="key", how="left")
    else:
        sub["total_pop"], sub["senior_pop"] = 0.0, 0.0
    sub[["total_pop", "senior_pop"]] = sub[["total_pop", "senior_pop"]].fillna(0.0)

    workers = load_workers_by_planning_area()
    area_total = sub.groupby("planning_area")["area"].transform("sum").replace(0, np.nan)
    pa_workers = sub["planning_area"].map(workers).fillna(0.0)
    sub["workers"] = (pa_workers * sub["area"] / area_total).fillna(0.0)
    # The census file also has non-geographic rows (works from home, no fixed
    # location, ...), which cannot be placed on a map.
    non_geographic = ("NO FIXED LOCATION FOR WORK", "OTHER PLANNING AREAS OR OUTSIDE SINGAPORE", "WORKS FROM HOME")
    missing = sorted(set(workers.index) - set(sub["planning_area"]) - set(non_geographic))
    if missing:
        print(f"  [warn] worker planning areas with no matching subzones (workers dropped): {missing}")
    return sub


def kernel_catchments(malls: pd.DataFrame, sub: pd.DataFrame, cols: list[str],
                      radius_m: float = REACH_KERNEL_RADIUS_M) -> pd.DataFrame:
    """Distance-weighted sum of each `cols` value over subzone centroids: a
    subzone counts fully at the mall and fades linearly to nothing at
    radius_m. Unlike a hard 1.2km circle, a subzone whose centroid sits just
    outside the line no longer vanishes, and nearby people count for more."""
    slat = sub["lat"].to_numpy(dtype=float)
    slon = sub["lon"].to_numpy(dtype=float)
    values = {c: sub[c].to_numpy(dtype=float) for c in cols}
    out = {c: np.zeros(len(malls)) for c in cols}
    for i, mall in enumerate(malls.itertuples()):
        w = np.clip(1.0 - haversine_m(mall.lat, mall.lon, slat, slon) / radius_m, 0.0, 1.0)
        for c in cols:
            out[c][i] = float((w * values[c]).sum())
    return pd.DataFrame(out, index=malls.index)


def station_access(malls: pd.DataFrame, exits: pd.DataFrame,
                   radius_m: float = CATCHMENT_RADIUS_M) -> pd.DataFrame:
    """Transit access by STATION, not by exit. The LTA file has one row per
    exit, so an interchange with eight exits used to look like eight stations.
    Per mall: how many distinct stations lie within radius_m, the distance to
    the nearest one, and a distance-decayed station count (each station
    contributes 1 - distance/radius, using its nearest exit)."""
    cols = ["mrt_count", "mrt_nearest_m", "mrt_access_index"]
    if exits.empty or "STATION_NA" not in exits.columns:
        return pd.DataFrame(0.0, index=malls.index, columns=cols)
    station = exits["STATION_NA"].fillna("").astype(str).str.strip().str.upper()
    lat, lon = exits["lat"].to_numpy(dtype=float), exits["lon"].to_numpy(dtype=float)
    rows = []
    for mall in malls.itertuples():
        d = pd.Series(haversine_m(mall.lat, mall.lon, lat, lon)).groupby(station.to_numpy()).min()
        rows.append({
            "mrt_count": int((d <= radius_m).sum()),
            "mrt_nearest_m": float(d.min()),
            "mrt_access_index": float(np.clip(1.0 - d / radius_m, 0.0, 1.0).sum()),
        })
    return pd.DataFrame(rows, index=malls.index)


def decayed_count(malls: pd.DataFrame, points: pd.DataFrame, radius_m: float) -> np.ndarray:
    """Distance-decayed count: each point within radius_m adds 1 - d/radius."""
    out = np.zeros(len(malls))
    if points.empty:
        return out
    plat = points["lat"].to_numpy(dtype=float)
    plon = points["lon"].to_numpy(dtype=float)
    for i, mall in enumerate(malls.itertuples()):
        out[i] = float(np.clip(1.0 - haversine_m(mall.lat, mall.lon, plat, plon) / radius_m, 0.0, 1.0).sum())
    return out


def dedupe_against(candidates: pd.DataFrame, existing: pd.DataFrame, within_m: float) -> pd.DataFrame:
    """Drop `candidates` (e.g. OSM gyms) lying within `within_m` of any
    `existing` point (e.g. the same gym in Gyms@SG), and collapse candidates
    that duplicate each other (OSM often maps a gym as both a node and a way)."""
    if candidates.empty:
        return candidates
    keep = np.ones(len(candidates), dtype=bool)
    clat = candidates["lat"].to_numpy(dtype=float)
    clon = candidates["lon"].to_numpy(dtype=float)
    if not existing.empty:
        elat, elon = existing["lat"].to_numpy(dtype=float), existing["lon"].to_numpy(dtype=float)
        for i in range(len(candidates)):
            if haversine_m(clat[i], clon[i], elat, elon).min() <= within_m:
                keep[i] = False
    for i in range(len(candidates)):
        if not keep[i]:
            continue
        dup = haversine_m(clat[i], clon[i], clat[i + 1:], clon[i + 1:]) <= within_m
        keep[i + 1:][dup] = False
    return candidates[keep].reset_index(drop=True)


def name_key(name: str) -> str:
    return "".join(name_tokens(name or ""))


def flag_existing_hpm(malls: pd.DataFrame) -> pd.Series:
    """1 for malls listed in data/manual/existing_hpm.csv (columns: name,
    source, optional match_as) -- HPB's existing Health Promoting Malls. The
    file is supplied by HPB CIP; with none, every mall is 0 and the dashboard
    says the index cannot be validated. Matched on name or any alias. The
    registry build adds any listed mall it does not already have
    (build_mall_registry.add_existing_hpms), so every entry should match."""
    flags = pd.Series(0, index=malls.index)
    path = MANUAL_DIR / "existing_hpm.csv"
    if not path.exists():
        return flags
    listed = pd.read_csv(path, dtype=str).fillna("")
    wanted: dict[str, str] = {}
    for rec in listed.itertuples(index=False):
        if not rec.name.strip():
            continue
        # `match_as` is the spelling used in the registry when it differs
        # from the one HPB uses ("Singpost Centre" -> "SingPost").
        for spelling in (rec.name, getattr(rec, "match_as", "")):
            if spelling.strip():
                wanted[name_key(spelling)] = rec.name
    if not wanted:
        return flags
    aliases = malls["aliases"].fillna("") if "aliases" in malls.columns else pd.Series("", index=malls.index)
    found = set()
    for idx, row in malls.iterrows():
        keys = {name_key(row["name"])} | {name_key(a) for a in str(aliases[idx]).split("; ") if a}
        hit = keys & set(wanted)
        if hit:
            flags[idx] = 1
            found |= hit
    unmatched = sorted({n for k, n in wanted.items() if k not in found} -
                       {n for k, n in wanted.items() if k in found})
    for n in unmatched:
        print(f"  [warn] existing_hpm.csv: '{n}' does not match any mall in the registry")
    return flags


def compute_untapped_demand(malls: pd.DataFrame, pop_catchment: np.ndarray,
                            point_sets: list[pd.DataFrame]) -> tuple[np.ndarray, np.ndarray, pd.Series]:
    """Engagement Gap ("untapped demand"): how FEW health-promoting amenities
    (healthier eateries, gyms/sport facilities, CHAS clinics) the 1.2km
    catchment has *for the number of residents it has*.

    A plain amenities-per-resident ratio is almost a function of population
    (Spearman ~0.8 with Reach & Population), which made population count
    twice in the Demand block. Instead we fit the typical amenity count for a
    given population -- log(amenities) = a + b*log(population) across all
    malls -- and score each mall by how far BELOW that expectation it sits.
    That residual is, by construction, uncorrelated with log-population, so
    this factor adds new information rather than repeating Reach.

    The residual is rank-scaled (the heavy tails would crush a min-max scale):
    the biggest shortfall scores 100, the biggest surplus 0. A mall with no
    resident population in its catchment has no meaningful gap, so its score
    is NaN ("n/a") and the index re-weights over that mall's remaining
    Demand factors instead of treating it as a hard zero. Community clubs
    (Category C) are intentionally excluded -- see the call site."""
    pts = pd.concat([p[["lat", "lon"]] for p in point_sets if not p.empty], ignore_index=True)
    amenities = count_nearby(malls, pts, CATCHMENT_RADIUS_M)
    pop = np.asarray(pop_catchment, dtype=float)
    has_pop = pop > 0
    per_10k = np.where(has_pop, amenities / np.where(has_pop, pop, 1) * 10_000, np.nan)

    gap = pd.Series(np.nan, index=range(len(malls)))
    fit = has_pop & (amenities > 0)
    if fit.sum() >= 3:
        x, y = np.log(pop[fit]), np.log(amenities[fit].astype(float))
        slope, intercept = np.polyfit(x, y, 1)
        residual = pd.Series(y - (intercept + slope * x))
        ranks = residual.rank(method="average", ascending=True)  # biggest shortfall = rank 1
        gap.loc[np.flatnonzero(fit)] = ((len(residual) - ranks) / max(len(residual) - 1, 1) * 100).to_numpy()
    gap.loc[np.flatnonzero(has_pop & (amenities == 0))] = 100.0  # residents, zero amenities: max gap
    return amenities, per_10k, gap


def compute_category_f(malls: pd.DataFrame) -> pd.Series:
    """Partnership Readiness proxy: portfolio scale of the mall's landlord
    group (a larger chain is more likely to have centralised CSR/health-
    programme capacity) plus a bonus for malls flagged `hpb_partner` -- a
    confirmed HPB partnership, supplied via data/manual/operators.csv (the
    registry build copies the flag into malls.csv). The operator column has
    already been merged into landlord groups by the registry build (see
    data/manual/operator_aliases.csv), so e.g. all CapitaLand trust names
    count as one portfolio. Malls with an "Unknown" operator count as a
    portfolio of one."""
    chain_size = malls.groupby("operator")["operator"].transform("count")
    chain_size = chain_size.where(malls["operator"] != "Unknown", 1)
    chain_score = min_max_normalize(chain_size)

    if "hpb_partner" in malls.columns:
        partner = malls["hpb_partner"].fillna(0).astype(float) > 0
    else:  # registry built before the manual operators table existed
        partner = malls["name"].map(normalize_name) == normalize_name("Downtown East")
    bonus = partner.astype(float) * 20

    return (chain_score * 0.8 + bonus).clip(upper=100)


def write_matching_qa() -> None:
    """Report name-equality matches that were rejected for being too far from
    the mall. Each row is a mall whose own building (by name) sits well away
    from where it was geocoded -- fix the geocode in
    data/manual/geocode_overrides.csv."""
    qa = pd.DataFrame(FAR_NAME_MATCHES, columns=["dataset", "mall", "n_far_name_matches", "max_distance_m"])
    qa.sort_values("n_far_name_matches", ascending=False).to_csv(PROCESSED_DIR / "matching_qa.csv", index=False)
    if qa.empty:
        print("  [qa] no name-matched amenity lies >%dm from its mall" % NAME_MATCH_MAX_M)
    else:
        print(f"  [qa] {qa['mall'].nunique()} malls have name-matched amenities >{NAME_MATCH_MAX_M}m away "
              "(possible bad geocode) -- see data/processed/matching_qa.csv")


def build_category_scores() -> pd.DataFrame:
    malls_path = PROCESSED_DIR / "malls.csv"
    malls = pd.read_csv(malls_path, dtype={"postal_code": str})
    print(f"Loaded {len(malls)} malls from {malls_path}")
    FAR_NAME_MATCHES.clear()

    out = malls[["mall_id", "name", "region", "operator", "lat", "lon"]].copy()
    out["operator_known"] = (malls["operator"] != "Unknown").astype(int)

    print("Assigning authoritative region (nearest URA subzone) ...")
    subzone_centroids = load_subzone_centroids()
    out["region"] = assign_region(malls, subzone_centroids)
    out["planning_area"] = assign_planning_area(malls, subzone_centroids).str.title()
    out["is_existing_hpm"] = flag_existing_hpm(malls)

    print("Category A - Healthy Dining Ecosystem (incl. supermarkets) ...")
    dining = load_points("healthier_eateries.geojson")
    # The HPB file repeats some outlets verbatim (same name, postal code and
    # coordinates) -- count each outlet once.
    dining = dining.drop_duplicates(
        subset=[c for c in ("ADDRESSPOSTALCODE", "NAME", "lat", "lon") if c in dining.columns]
    ).reset_index(drop=True)
    dining_partners = load_deduped_partner_addresses(dining)
    # NEA's licence list has no single address field -- build one from its
    # separate building_name/block_house_num/street_name columns.
    supermarkets = load_csv_addresses(
        "supermarket_licences.csv", ["building_name", "block_house_num", "street_name"]
    )
    out["A_supermarket_count"] = count_by_address_text(malls, supermarkets)
    eatery_counts = count_nearby(malls, dining, ON_SITE_RADIUS_M, "ADDRESSBUILDINGNAME",
                                 label="healthier_eateries", exclusive=True)
    out["A_dining_count"] = (
        eatery_counts + count_by_address_text(malls, dining_partners) + out["A_supermarket_count"]
    )
    out["A_dining_score"] = min_max_normalize(out["A_dining_count"])

    # Diagnostics for the charter's "% of F&B outlets" metric. NOT part of the
    # index: OpenStreetMap's F&B coverage inside malls is patchy, so the share
    # can only be trusted once HPB CIP has reviewed it (see the Methodology page).
    fnb = load_points("osm_fnb.geojson")
    out["A_hdp_outlets"] = eatery_counts
    out["A_fnb_osm_count"] = count_nearby(malls, fnb, ON_SITE_RADIUS_M, exclusive=True)
    reliable = out["A_fnb_osm_count"] >= 5
    out["A_healthier_share"] = (out["A_hdp_outlets"] / out["A_fnb_osm_count"].where(reliable)).round(3)

    print("Category B - Physical Activity Ecosystem ...")
    official_fitness = pd.concat([
        load_points("gyms_at_sg.geojson"),
        load_points("sportsg_sport_facilities.geojson"),
    ], ignore_index=True)
    # Gyms@SG only lists HPB-registered gyms; OpenStreetMap adds commercial
    # gyms and studios. OSM points duplicating a listed venue are dropped.
    osm_fitness = dedupe_against(load_points("osm_fitness.geojson"), official_fitness, OSM_DEDUPE_M)
    fitness = pd.concat([official_fitness, osm_fitness], ignore_index=True)
    out["B_osm_fitness_count"] = count_nearby(malls, osm_fitness, ON_SITE_RADIUS_M, exclusive=True)
    out["B_fitness_count"] = count_nearby(malls, fitness, ON_SITE_RADIUS_M, exclusive=True)
    out["B_fitness_score"] = min_max_normalize(out["B_fitness_count"])

    print("Category C - H365 & HPB Engagement (community-club proxy) ...")
    community = load_points("community_clubs.geojson")
    out["C_engagement_count"] = count_nearby(malls, community, NEARBY_RADIUS_M)
    out["C_engagement_score"] = min_max_normalize(out["C_engagement_count"])

    print("Category D - Healthcare Ecosystem ...")
    healthcare = load_points("chas_clinics.geojson")
    pharmacies = load_csv_addresses("licensed_pharmacies.csv", "PharmacyAddress")
    out["D_healthcare_count"] = (
        count_nearby(malls, healthcare, ON_SITE_RADIUS_M, "BUILDING_NAME", label="chas_clinics", exclusive=True)
        + count_by_address_text(malls, pharmacies)
    )
    out["D_healthcare_score"] = min_max_normalize(out["D_healthcare_count"])

    print("Category E - Healthy Infrastructure (parks + bicycle racks) ...")
    park_facilities = load_points("park_facilities.geojson")
    if "CLASS" in park_facilities.columns:
        park_facilities = park_facilities[
            park_facilities["CLASS"].astype(str).str.upper().str.strip().isin(PARK_FACILITY_CLASSES)
        ]
    infra = pd.concat([load_points("parks_at_sg.geojson"), park_facilities], ignore_index=True)
    bike_racks = load_points("bicycle_racks.geojson")
    out["E_bike_rack_count"] = count_nearby(malls, bike_racks, ON_SITE_RADIUS_M, exclusive=True)
    out["E_infra_count"] = count_nearby(malls, infra, NEARBY_RADIUS_M) + out["E_bike_rack_count"]
    out["E_infra_score"] = min_max_normalize(out["E_infra_count"])

    print("Category F - Landlord & Partnership Readiness (operator proxy) ...")
    out["F_partnership_score"] = compute_category_f(malls)

    print("Demand side - population catchment, accessibility ...")
    # Residents in a hard 1.2km circle: kept for the Engagement Gap, whose
    # amenity counts use the same circle.
    total_pop, senior_pop = compute_population_catchment(malls, subzone_centroids)
    out["pop_catchment"] = total_pop
    out["senior_pop_catchment"] = senior_pop

    # Reach & Population uses a distance-weighted catchment instead, and adds
    # workers (the charter's "worker population") so CBD / airport / office
    # malls are not scored as if nobody were ever there.
    sub = build_subzone_table(subzone_centroids)
    reach = kernel_catchments(malls, sub, ["total_pop", "senior_pop", "workers"])
    out["pop_reach_weighted"] = reach["total_pop"].round(0)
    out["senior_reach_weighted"] = reach["senior_pop"].round(0)
    out["worker_reach_weighted"] = reach["workers"].round(0)
    out["reach_population_score"] = (
        min_max_normalize(reach["total_pop"]) * 0.5
        + min_max_normalize(reach["senior_pop"]) * 0.3
        + min_max_normalize(reach["workers"]) * 0.2
    )
    # Catchments with more (distance-weighted) workers than residents.
    out["daytime_led"] = (reach["workers"] > reach["total_pop"]).astype(int)

    mrt = load_points("mrt_station_exits.geojson")
    bus = load_points("bus_stops.geojson")
    stations = station_access(malls, mrt)
    out["mrt_count"] = stations["mrt_count"].astype(int)
    out["mrt_nearest_m"] = stations["mrt_nearest_m"].round(0)
    out["mrt_access_index"] = stations["mrt_access_index"].round(3)
    out["bus_count"] = count_nearby(malls, bus, BUS_RADIUS_M)
    out["bus_access_index"] = decayed_count(malls, bus, BUS_RADIUS_M).round(3)
    out["accessibility_score"] = (
        min_max_normalize(out["mrt_access_index"]) * 0.5 + min_max_normalize(out["bus_access_index"]) * 0.5
    )

    # Engagement Gap ("untapped demand"): charter lists "low healthy dining
    # exposure" and "under-served health promotion locations". Scored as how
    # few health-promoting amenities the catchment has per resident -- this is
    # deliberately independent of Category C (community clubs) so the demand
    # block doesn't simply mirror/cancel a supply category.
    area_amenities, per_10k, gap = compute_untapped_demand(
        malls, total_pop,
        [dining, fitness, healthcare],
    )
    out["area_health_amenities"] = area_amenities
    out["area_amenities_per_10k_residents"] = per_10k
    out["engagement_gap_score"] = gap

    write_matching_qa()

    out_path = PROCESSED_DIR / "category_scores.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {len(out)} malls x category scores to {out_path}")
    return out


if __name__ == "__main__":
    build_category_scores()
