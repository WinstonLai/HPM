# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pure-Python data pipeline + Streamlit dashboard that scores and ranks Singapore
shopping malls on readiness to become HPB "Health Promoting Malls," per the
*Health Promoting Mall Readiness Assessment Project Charter*
(`Health Promoting Mall Readiness Assessment Project Charter 20260904.docx`).

```
HPM Index = Supply Readiness (70%) + Demand Opportunity (30%)
Supply Readiness  = Dining + Fitness + H365 Presence + Healthcare
                     + Infrastructure + Partnership Readiness
Demand Opportunity = Reach & Population + Accessibility + Engagement Gap
```

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Full ETL rebuild (one-off, ~10-15 min: Wikipedia scrape + OneMap geocoding +
# throttled data.gov.sg downloads). Re-run any time to refresh the data.
python etl/run_all.py
python etl/run_all.py --force          # re-download/re-scrape even if cached
python etl/run_all.py --limit 10       # cap mall count, for a fast debug run

# Individual ETL stages (each reads/writes data/{raw,processed}/, safe to run alone)
python etl/build_mall_registry.py [--limit N]   # -> data/processed/malls.csv
python etl/build_amenities.py [--force]         # -> data/raw/*.geojson|csv
python etl/build_category_scores.py             # -> data/processed/category_scores.csv
python etl/build_index.py                       # -> data/processed/hpm_index.csv

# Dashboard
streamlit run app/Home.py

# Sanity-check all Python files compile
python -m py_compile etl/*.py app/*.py app/lib/*.py app/pages/*.py
```

There is no test suite, linter config, or CI in this repo. `data/processed/*.csv`
is committed (so the dashboard runs without an ETL pass); `data/raw/` is
gitignored (large cached downloads, rebuildable via the ETL scripts).

## Architecture

Two independent halves connected only through `data/processed/*.csv`:

1. **`etl/`** — one-off/rerunnable pipeline, run from the command line, no
   Streamlit dependency. `run_all.py` orchestrates four stages in order, each
   writing a CSV the next stage reads:
   - `build_mall_registry.py` scrapes THREE Wikipedia sources and unions +
     de-dupes them by normalized name — the region-organised "List of
     shopping malls in Singapore" article alone only yields ~95 malls, well
     short of the 180+ business users expect, so it's combined with every
     article in `Category:Shopping malls in Singapore` (broader; the
     `categorymembers` API naturally excludes the "Defunct shopping malls"
     subcategory since it only returns direct members) and the "Housing
     estate commercial areas" section of "List of commercial sites in
     Singapore" (neighbourhood centres, some plain-text with no Wikipedia
     article). Combined this yields ~230 candidates → 185 after failed
     geocodes are dropped. Uses wikitext parsing, not HTML — the live page's
     rendered HTML wraps mall lists in Parsoid `data-mw` transclusion JSON
     with no `<a>` tags, so `action=parse&prop=wikitext` is used instead.
     Each mall's own article is fetched for its infobox operator/owner field
     (most of the 185 have no infobox and end up "Unknown" — this is
     genuine data sparsity, not a scraping bug), and every mall is geocoded
     via OneMap → `data/processed/malls.csv`.
   - `build_category_scores.py` also assigns the authoritative `region`
     (nearest URA Master Plan subzone centroid) for every mall, overriding
     whatever region a mall's Wikipedia source gave it — most of the 185
     don't carry one at scrape time since only the first of the three
     sources above is region-organised.
   - `build_amenities.py` downloads the ~11 raw datasets (dataset IDs are
     defined here, grouped by category A–G) → `data/raw/`.
   - `build_category_scores.py` joins every raw dataset to the mall registry
     and produces one normalized 0–100 score per category (A–G) per mall →
     `data/processed/category_scores.csv`.
   - `build_index.py` applies the charter's illustrative weights to produce
     the default ranked view → `data/processed/hpm_index.csv`.

   Shared helpers: `datagovsg.py` (throttled/retried data.gov.sg download
   client — unauthenticated callers are rate-limited to ~5 req/min, so calls
   are paced ~13s apart; also normalizes the two GeoJSON property shapes
   agencies actually publish — clean `properties` vs. legacy KML
   `Description` HTML-table blobs), `onemap.py` (OneMap Search API geocoding,
   no API key needed), `geo.py` (haversine distance, polygon centroid,
   min-max normalization — deliberately no geopandas/shapely dependency).

2. **`app/`** — the Streamlit dashboard, reads only `data/processed/*.csv`,
   never calls external APIs live. `Home.py` is the entrypoint (Page 1 —
   Executive Summary); `app/pages/` holds Pages 2–6 (National Ranking,
   What-If Simulator, Mall Comparison, National Map, Strategic Matrix — a
   2×2 Readiness×Demand quadrant enhancement). Each page file does its own
   `sys.path.insert` to reach `app/lib/` (there's no package `__init__.py`;
   pages are run as standalone scripts by Streamlit).

**`etl/scoring_formula.py` is the single source of truth for the composite
index formula.** It's imported both by `build_index.py` (the offline default
ranking) and by `app/lib/scoring.py` (a thin wrapper the What-If Simulator
page uses to recompute the index live from slider weights) — this guarantees
a weight change in the UI and the offline build always agree on how a score
is computed. Any change to the weighting/scoring math belongs in that one
file.

### Mall-to-amenity matching strategy (in `build_category_scores.py`)

Amenity datasets get matched to malls one of two ways, chosen per dataset
based on what fields it actually publishes:

- Datasets with a clean building-name field (`ADDRESSBUILDINGNAME`,
  `BUILDING_NAME`) are matched by normalized name equality, then everything
  is *also* checked by haversine distance so on-site amenities with slightly
  different naming still count. Radii: 200m "on-site" (dining/fitness/
  healthcare), 500m "nearby" (community clubs/parks), 1.2km demand-side
  catchment (population/MRT/bus).
- Two data.gov.sg datasets (Healthier Dining Partners, Licensed Pharmacies)
  are published as plain CSV with a free-text address and no coordinates at
  all — despite `.geojson`-sounding names, always check the actual file
  content before assuming format. These are matched by substring-matching
  the normalized mall name inside the address text (`count_by_address_text`).

Every raw count is min-max normalized to 0–100 across the mall population
(not divided by each mall's total tenant count, which the charter's own
worked example uses — that needs a per-mall tenant directory that doesn't
publicly exist). See the README's "Known proxies / limitations" section for
the specific proxies used for Category C (H365 engagement → community-club
density) and Category F (partnership readiness → scraped operator portfolio
size), and don't present those proxy scores as the literal metric named in
the charter without that caveat.

## Data sources

All data.gov.sg datasets are pulled live via the current
`api-open.data.gov.sg/v1/public/api/datasets/{id}/poll-download` API (no key
required for this volume; throttled to respect the ~5 req/min unauthenticated
limit). Exact dataset IDs live in `etl/build_amenities.py`'s `DATASETS` dict,
grouped by charter category (A–G). Full source table and per-category
methodology/limitations are in `README.md` — read it before changing which
dataset backs a category or how a category is scored.
