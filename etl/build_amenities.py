"""Download all raw amenity/context datasets used by the HPM index from
data.gov.sg. Every dataset ID below was verified live against the current
api-open.data.gov.sg download API. Cached under data/raw/ so re-runs are
fast and don't re-hit the (rate-limited) API.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datagovsg import fetch_dataset  # noqa: E402

# category -> list of (dataset_id, filename, publisher)
DATASETS: dict[str, list[tuple[str, str, str]]] = {
    "A_dining": [
        ("d_2925c2ccf75d1c135c2d469e0de3cee6", "healthier_eateries.geojson", "HPB"),
        # NB: despite the dataset name suggesting geospatial data, this one is
        # published as a plain CSV with a free-text outlet address (no lat/lon).
        ("d_c475b9170c08f90580f4041bffd51639", "healthier_dining_fnb_partners.csv", "HPB"),
        # Plain CSV, no coordinates: building_name/block/street/postal_code columns.
        ("d_11edd0117280c5776651d7891114c88c", "supermarket_licences.csv", "NEA"),
    ],
    "B_fitness": [
        ("d_b3ae090692ecf632116c9885cfbd3424", "gyms_at_sg.geojson", "HPB"),
        ("d_9b87bab59d036a60fad2a91530e10773", "sportsg_sport_facilities.geojson", "SportSG"),
    ],
    "C_engagement": [
        ("d_9de02d3fb33d96da1855f4fbef549a0f", "community_clubs.geojson", "People's Association"),
    ],
    "D_healthcare": [
        ("d_548c33ea2d99e29ec63a7cc9edcccedc", "chas_clinics.geojson", "MOH"),
        # Also a plain CSV with a free-text address, not GeoJSON.
        ("d_bc50d72a9d61457964c6ea8d8ba7dce2", "licensed_pharmacies.csv", "HSA"),
    ],
    "E_infrastructure": [
        ("d_99b71f5d34cf57a3a592fbfdef1f42b6", "parks_at_sg.geojson", "HPB"),
        ("d_14d807e20158338fd578c2913953516e", "park_facilities.geojson", "NParks"),
        ("d_937424cca6d1617288a82a7aeb89f76d", "bicycle_racks.geojson", "LTA"),
    ],
    "G_demand": [
        ("d_d95ae740c0f8961a0b10435836660ce0", "resident_population_2020.csv", "SingStat"),
        ("d_8594ae9ff96d0c708bc2af633048edfb", "subzone_boundary.geojson", "URA"),
        ("d_b39d3a0871985372d7e1637193335da5", "mrt_station_exits.geojson", "LTA"),
        ("d_3f172c6feb3f4f92a2f47d93eed2908a", "bus_stops.geojson", "LTA"),
    ],
}


def download_all(force: bool = False) -> None:
    for category, items in DATASETS.items():
        for dataset_id, filename, publisher in items:
            print(f"[{category}] fetching {filename} ({publisher}) ...")
            try:
                path = fetch_dataset(dataset_id, filename, force=force)
                print(f"  -> {path} ({path.stat().st_size / 1024:.0f} KB)")
            except Exception as exc:  # noqa: BLE001
                print(f"  [error] {filename}: {exc}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    args = parser.parse_args()
    download_all(force=args.force)
