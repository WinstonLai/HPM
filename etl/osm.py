"""OpenStreetMap points via the public Overpass API, for the two things no
government dataset covers: commercial fitness venues (Category B) and food &
beverage outlets (a size denominator for the Category A diagnostics).

Results are cached under data/raw/ like the data.gov.sg downloads, as a
GeoJSON FeatureCollection of Point features (ways/relations are reduced to
their centre) so `build_category_scores.load_points` reads them unchanged.
Overpass rejects requests without a descriptive User-Agent (HTTP 406).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from datagovsg import is_valid_download, write_validated

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "HPM-readiness-poc/1.0 (contact: hpb-cip-poc)"}
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
SG_AREA = 'area["ISO3166-1"="SG"][admin_level=2]->.sg;'

# name -> Overpass selector body (everything inside the Singapore area)
QUERIES: dict[str, str] = {
    # gyms, fitness studios, sports halls/centres
    "osm_fitness.geojson": 'nwr["leisure"~"^(fitness_centre|sports_centre)$"](area.sg);'
                           'nwr["amenity"="gym"](area.sg);',
    # restaurants, cafes, fast food, food courts: denominator for % healthier
    "osm_fnb.geojson": 'nwr["amenity"~"^(restaurant|cafe|fast_food|food_court)$"](area.sg);',
}


def _to_geojson(elements: list[dict]) -> dict:
    feats = []
    for el in elements:
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags") or {}
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"NAME": tags.get("name", ""), "BRAND": tags.get("brand", ""),
                           "KIND": tags.get("leisure") or tags.get("amenity") or "",
                           "OSM_ID": f"{el.get('type')}/{el.get('id')}"},
        })
    return {"type": "FeatureCollection", "features": feats}


def fetch_osm(filename: str, force: bool = False, attempts: int = 4) -> Path:
    """Download (or reuse the cached copy of) one OSM extract."""
    dest = RAW_DIR / filename
    if dest.exists() and not force:
        if is_valid_download(dest):
            return dest
        print(f"  [warn] cached {filename} is incomplete or invalid; downloading again")
    query = f"[out:json][timeout:120];{SG_AREA}({QUERIES[filename]});out center tags;"
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS, timeout=180)
            if resp.status_code in (429, 504):
                time.sleep(20 * (attempt + 1))
                continue
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            if not elements:   # Overpass answers 200 with a "remark" and no elements when a query times out
                raise ValueError("Overpass returned no elements")
            write_validated(dest, lambda tmp: tmp.write_text(json.dumps(_to_geojson(elements))))
            return dest
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last = exc
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass failed for {filename} after {attempts} attempts: {last}")


def download_all(force: bool = False) -> list[str]:
    """Fetch every extract; returns the filenames that failed."""
    failed: list[str] = []
    for filename in QUERIES:
        print(f"[osm] fetching {filename} ...")
        try:
            path = fetch_osm(filename, force=force)
            n = len(json.loads(path.read_text())["features"])
            print(f"  -> {path} ({n} points)")
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] {filename}: {exc}")
            failed.append(filename)
    return failed
