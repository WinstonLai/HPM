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
python etl/run_all.py --limit 10       # cap mall count, for a fast debug run; writes to
                                       # data/processed_limited/ (gitignored), never data/processed/
python etl/run_all.py --allow-missing  # carry on past a failed download (default: stop, since a
                                       # missing dataset would otherwise score its category as 0)

# Individual ETL stages (each reads/writes data/{raw,processed}/, safe to run alone)
python etl/build_mall_registry.py [--limit N]   # -> data/processed/malls.csv (--limit: data/processed_limited/)
python etl/build_amenities.py [--force]         # -> data/raw/*.geojson|csv
python etl/build_category_scores.py             # -> data/processed/category_scores.csv
python etl/build_index.py                       # -> data/processed/hpm_index.csv

# Dashboard
streamlit run app/Home.py

# Sanity-check all Python files compile
python -m py_compile etl/*.py app/*.py app/lib/*.py app/pages/*.py

# Tests (ETL logic: geocode validation, matching, scoring, registry merging, validators)
pip install -r requirements-dev.txt && pytest

# Cheap registry maintenance (no re-scrape / re-geocode)
python etl/build_mall_registry.py --add-existing-hpms   # after editing data/manual/existing_hpm.csv
python etl/build_mall_registry.py --refresh-types       # after editing data/manual/mall_types.csv
python etl/build_mall_registry.py --dedupe              # merge duplicate malls in the current malls.csv
```

There is a pytest suite for the ETL logic (`tests/`) but no linter config or CI.
Each stage validates its output (`etl/validate.py`) and records provenance in
`data/processed/_meta.json` (`etl/provenance.py`). `data/processed/*.csv`
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
     article). Combined this yields ~215 candidates → ~173 after duplicates
     are merged and unverifiable geocodes are dropped (see `registry_qa.csv`). Uses wikitext parsing, not HTML — the live page's
     rendered HTML wraps mall lists in Parsoid `data-mw` transclusion JSON
     with no `<a>` tags, so `action=parse&prop=wikitext` is used instead.
     Each mall's own article is fetched (redirects followed) for its infobox
     owner/management/developer field (most malls have no infobox and end up
     "Unknown" — this is genuine data sparsity, not a scraping bug), cleaned
     through `data/manual/operator_aliases.csv` and overridden by
     `data/manual/operators.csv` where HPB CIP has supplied facts. Every
     mall is geocoded via OneMap → `data/processed/malls.csv`.
     **Geocodes are validated**: OneMap's top hit is often the wrong
     building, so `onemap.geocode_validated` walks all candidates and
     accepts only one whose BUILDING text matches the mall name; malls with
     no match are dropped into `data/processed/registry_qa.csv` unless
     `data/manual/geocode_overrides.csv` fixes them. Duplicates are merged
     before and after geocoding (`aliases` column keeps the other names),
     `mall_id` is a slug, and `postal_code` is a zero-padded string — read it
     with `dtype={"postal_code": str}`.
   - `build_category_scores.py` also assigns the authoritative `region`
     (nearest URA Master Plan subzone centroid) for every mall, overriding
     whatever region a mall's Wikipedia source gave it — most malls
     don't carry one at scrape time since only the first of the three
     sources above is region-organised.
   - `build_amenities.py` downloads the 16 raw data.gov.sg datasets plus two
     OpenStreetMap extracts (`osm.py`, Overpass API; commercial gyms and F&B
     outlets). Dataset IDs are
     defined here, grouped by category A–G, excluding F which is a scraped
     proxy with no downloadable dataset) → `data/raw/`.
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
   Executive Summary); `app/pages/` holds Pages 2–8 (National Ranking,
   What-If Simulator, Mall Comparison, National Map, Strategic Matrix — a
   2×2 Readiness×Demand quadrant enhancement — Methodology, an
   interactive walkthrough of the scoring math, data-source limitations and
   weight robustness — and Regional Priorities, a region/planning-area and
   landlord rollup plus a backtest against existing HPMs).
   Each page file does its own `sys.path.insert` to reach `app/lib/`
   (there's no package `__init__.py`; pages are run as standalone scripts
   by Streamlit).

**Custom weights are shared across pages.** The What-If Simulator saves its
settings under a plain `st.session_state` key (`app/lib/weights.py`), because
Streamlit drops slider values when their page is not rendered; every page gets
its ranking from `weights.load_index()` (default CSV unless settings differ) and
shows `weights.show_banner()`. Tiers are fixed cut-offs on the HPM Index
(`TIER_THRESHOLDS`), not rank quartiles.

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
  healthcare/bicycle racks), 500m "nearby" (community clubs/parks), 1.2km
  demand-side catchment (population/MRT/bus).
- Three data.gov.sg datasets (Healthier Dining Partners, Licensed
  Pharmacies, Supermarket Licences) are published as plain CSV with a
  free-text address and no coordinates at all — despite `.geojson`-sounding
  names, always check the actual file content before assuming format.
  These are matched by word-boundary substring-matching the mall's full
  name inside the address text (`count_by_address_text`).
- **Trap**: `count_by_address_text` uses `normalize_name_strict`
  (keeps spaces as boundaries, doesn't strip generic suffix words), *not*
  the lenient `normalize_name` used for building-name equality. Reusing the
  lenient one here breaks badly for any mall whose name reduces to a common
  word once "Mall"/"Plaza"/etc. is stripped — e.g. "West Mall" → "west"
  used to match nearly any address in western Singapore (Jurong West,
  Sengkang West, ...), and "Tampines Mall" → "tampines" matched any address
  merely located in the town of Tampines. If you add another free-text
  address dataset, use `normalize_name_strict`, not `normalize_name`.

- **Trap**: building-name *equality* matching (`count_nearby`) is bounded
  to `NAME_MATCH_MAX_M` (500m) and skipped for name keys shared by several
  malls — the lenient key collapses "Rivervale Plaza"/"Rivervale Mall" and
  "Tampines Mall"/"Tampines Plaza" to one word. Rejected far matches go to
  `data/processed/matching_qa.csv`; a mall listed there probably has a bad
  geocode.

Every raw count is capped at the 95th percentile (`geo.WINSOR_QUANTILE`) and
then min-max normalized to 0–100 across the mall population (not divided by each mall's total tenant count, which the charter's own
worked example uses — that needs a per-mall tenant directory that doesn't
publicly exist). See the README's "Known proxies / limitations" section for
the specific proxies used for Category C (H365 engagement → community-club
density) and Category F (partnership readiness → scraped operator portfolio
size), and don't present those proxy scores as the literal metric named in
the charter without that caveat.

Other deliberate scoring choices to preserve (details in the README's
limitations section): Category E only counts NParks `PLAYGROUND`/`FITNESS AREA`/
`DRINKING FOUNTAIN`/`FOOT RELAX` rows (the file is mostly carparks/noticeboards);
on-site amenities (dining, gyms, clinics, bike racks) are assigned to their
*nearest* mall only (`count_nearby(exclusive=True)`); MRT access is counted per
*station* with distance decay, not per exit; Reach & Population is a
distance-weighted catchment of residents, seniors and workers (the Engagement
Gap keeps the hard 1.2km circle to match its amenity counts); the 48 existing
HPMs in `data/manual/existing_hpm.csv` drive both `is_existing_hpm` and
`add_existing_hpms`, which adds any listed mall the Wikipedia registry lacks
(14 were missing) — run `python etl/build_mall_registry.py --add-existing-hpms`
after editing that file, instead of a full re-scrape; Category A drops Healthier
Dining Partner outlets that duplicate a Healthier Eatery (postal code + brand);
Engagement Gap is the *shortfall* of 1.2km-catchment amenities versus the
amount expected for that population (a log-log fit), rank-scaled — not a raw
amenities-per-resident ratio, which is ~0.8 correlated with Reach &
Population and made population count twice. It is independent of Category C
(don't redefine it as `100 - C`, which cancels C's Supply contribution). A mall
with no residents nearby gets NaN, and `scoring_formula._weighted_sum`
re-weights over the non-NaN factors instead of scoring it 0. Categories C and
F are proxies and start with lower default weights (10 / 5 vs the charter's
15 / 10, kept in `CHARTER_SUPPLY_WEIGHTS`); the What-If page can drop them
via `exclude_proxies`. After changing any of these, rebuild with
`python etl/build_category_scores.py && python etl/build_index.py` and commit
the refreshed `data/processed/*.csv`, since the Methodology page quotes them.

## Data sources

All data.gov.sg datasets are pulled live via the current
`api-open.data.gov.sg/v1/public/api/datasets/{id}/poll-download` API (no key
required for this volume; throttled to respect the ~5 req/min unauthenticated
limit). Exact dataset IDs live in `etl/build_amenities.py`'s `DATASETS` dict,
grouped by charter category (A–G). Full source table and per-category
methodology/limitations are in `README.md` — read it before changing which
dataset backs a category or how a category is scored.
