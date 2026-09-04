# Health Promoting Mall (HPM) Readiness Dashboard

A pure-Python data pipeline + interactive dashboard that scores and ranks
Singapore shopping malls on their readiness to become HPB "Health Promoting
Malls," per the *Health Promoting Mall Readiness Assessment Project Charter*.

```
HPM Index = Supply Readiness (70%) + Demand Opportunity (30%)
Supply Readiness  = Dining + Fitness + H365 Presence + Healthcare
                     + Infrastructure + Partnership Readiness
Demand Opportunity = Reach & Population + Accessibility + Engagement Gap
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Build the data (one-off, ~10-15 min: Wikipedia scrape + OneMap geocoding
#    + throttled data.gov.sg downloads). Re-run any time to refresh.
python etl/run_all.py

# 2. Launch the dashboard
streamlit run app/Home.py
```

Processed data lives in `data/processed/*.csv` and is checked into the repo,
so `streamlit run app/Home.py` works immediately without re-running the ETL
step. Raw downloads are cached in `data/raw/` (gitignored) so re-running the
ETL is fast after the first pass.

## Pages

1. **Home** — executive summary: total malls assessed, average index, Top 10, top landlords.
2. **National Ranking** — full ranked table, filterable by region / operator / tier.
3. **What-If Simulator** — sliders for every category weight and the overall Supply/Demand split; ranking, tiers, and Top 10/20/50 shortlists recompute instantly.
4. **Mall Comparison** — radar chart + strengths/weaknesses for up to 5 malls.
5. **National Map** — mall locations coloured by score, with a shortlist toggle.
6. **Strategic Matrix** — 2×2 Readiness × Demand quadrant view (Pioneer HPM / Quick Wins / Strategic Investment / Future Monitoring), the charter's proposed enhancement over a flat ranking.
7. **Methodology** — plain-language explanation of the data sources, why raw counts are normalised, and the category weights, with an interactive worked example that recomputes any selected mall's actual score step by step (Supply contributions → Demand contributions → final index), plus a "what this score doesn't capture" section.

## Data sources

Every category is backed by at least one real, freely downloadable government
dataset — no scraping of anything other than Wikipedia and no data was
fabricated. All data.gov.sg datasets are pulled live via the current
`api-open.data.gov.sg` download API.

| Category | Datasets | Publisher |
|---|---|---|
| Mall registry | Three Wikipedia sources unioned + de-duplicated: "List of shopping malls in Singapore", `Category:Shopping malls in Singapore`, and the "Housing estate commercial areas" section of "List of commercial sites in Singapore" (185 malls) — geocoded via OneMap Search API | Wikipedia / OneMap (SLA) |
| A – Healthy Dining | Healthier Eateries, Healthier Dining Partners – F&B Partners, List of Supermarket Licences | HPB / NEA |
| B – Physical Activity | Gyms@SG, SportSG Sport Facilities | HPB / SportSG |
| C – H365 & HPB Engagement | Community Club / PAssion WaVe Outlet (proxy — see Limitations) | People's Association |
| D – Healthcare | CHAS Clinics, Listing of Licensed Pharmacies | MOH / HSA |
| E – Healthy Infrastructure | Parks@SG, Park Facilities, LTA Bicycle Rack | HPB / NParks / LTA |
| F – Landlord & Partnership Readiness | Operator scraped from Wikipedia infobox (proxy — see Limitations) | Wikipedia |
| G – Demand (Reach/Population/Accessibility) | Resident Population by Planning Area/Subzone (Census 2020), Master Plan 2019 Subzone Boundary, LTA MRT Station Exits, LTA Bus Stops | SingStat / URA / LTA |

Exact dataset IDs are in `etl/build_amenities.py`.

## Methodology

- **Matching amenities to malls**: datasets with a clean building-name field
  (e.g. `ADDRESSBUILDINGNAME`, `BUILDING_NAME`) are matched by normalised
  name equality; everything is additionally matched by straight-line
  (haversine) distance — 200m for on-site amenities (dining/fitness/
  healthcare/bicycle racks), 500m for "nearby" amenities (community
  clubs/parks), and 1.2km for demand-side catchment (population/MRT/bus).
  Three data.gov.sg datasets (Healthier Dining Partners, Licensed
  Pharmacies, Supermarket Licences) are published as plain CSV with only a
  free-text address and no coordinates; those are matched by word-boundary
  substring-matching the mall's full name inside the address (e.g. "West
  Mall" is matched as the phrase "west mall", not the bare word "west" —
  an earlier version stripped generic suffix words like "Mall"/"Plaza" for
  this match too, which caused "West Mall" to match almost any address
  containing "Jurong **West**" or "Sengkang **West**"; that bug also badly
  inflated "Tampines Mall"'s count via any address merely located in the
  town of Tampines. Building-name *equality* matching doesn't have this
  problem and still strips those suffix words, since that's what makes it
  tolerant of naming variants like "ABC Mall" vs "ABC Shopping Centre").
- **Normalisation**: every raw count is min-max scaled to 0–100 across the
  mall population, so a mall's score reflects its *relative* standing, not
  its raw size. This is a simplification of the charter's own worked example
  (which divides by each mall's *total* tenant count, e.g. "% of F&B outlets
  in HDP") — that formula needs a full per-mall tenant directory, which is
  not publicly available. Min-max scaling still fixes the core bias the
  charter warns about (a big mall's raw count no longer mechanically wins).
- **Region assignment**: every mall's `region` is the URA region of its
  *nearest* Master Plan subzone centroid (Central/East/North/North-East/
  West), computed after geocoding — not the region label from whichever
  Wikipedia source it came from (most of the 185 malls, sourced from the
  Wikipedia category and commercial-sites lists rather than the
  region-organised list article, don't carry one at scrape time). This keeps
  region consistent and data-driven across the whole registry regardless of
  source.
- **Composite index**: `etl/scoring_formula.py` is the single source of
  truth, used both by the offline ETL build and by the What-If Simulator, so
  a slider change and the default ranking are always computed the same way.

### Known proxies / limitations (documented, not hidden)

- **Category C (H365 & HPB Engagement)**: no public dataset of H365 event
  locations/frequency exists. Proxied by nearby Community Club / PAssion
  WaVe Outlet density, since CCs are a primary channel for HPB/community
  programming.
- **Category F (Partnership Readiness)**: no public partnership dataset
  exists — HPB's own website names only one confirmed partner (Downtown
  East). Proxied by the scraped mall operator's portfolio size (a bigger
  chain is more likely to have centralised CSR/health-programme capacity),
  plus a +20 bonus for the one confirmed partnership. Operator names are
  free text pulled from Wikipedia infoboxes and are not deduplicated across
  near-identical entity names (e.g. "CapitaLand Mall Trust" vs "CapitaLand
  Mall Trust Management").
- **Category A "% of F&B outlets in HDP"**: no public per-mall total-tenant-
  count dataset exists, so Category A is a density score (HDP outlets +
  Healthier Dining Partners + licensed supermarkets found near the mall),
  not a true participation percentage. Supermarket *presence* is included
  (NEA's List of Supermarket Licences), but there's no public dataset that
  flags which specific supermarkets carry HPB's "healthier choice" range —
  so this counts any licensed supermarket, not specifically ones "with
  healthier choice options" as the charter's measure names it.
- **Population catchment**: subzone population is apportioned to a mall if
  the subzone's polygon *centroid* (a simple vertex-average, not
  area-weighted) falls within 1.2km — an approximation that can miss a
  mall sitting at the edge of a large subzone.
- **Engagement Gap**: computed as `100 - Category C score`, per the
  charter's own definition of "untapped demand" as low existing engagement
  despite catchment potential.

## Repository layout

```
etl/                ETL pipeline (run_all.py orchestrates everything)
  datagovsg.py       data.gov.sg download client (throttled/retried)
  onemap.py          OneMap Search API geocoding
  geo.py             haversine distance, polygon centroid, min-max scaling
  scoring_formula.py single source of truth for the composite index formula
  build_mall_registry.py   Wikipedia scrape + geocoding -> malls.csv
  build_amenities.py       downloads all raw datasets -> data/raw/
  build_category_scores.py joins + normalises -> category_scores.csv
  build_index.py           applies default weights -> hpm_index.csv
app/                 Streamlit dashboard
  Home.py            Page 1 - Executive Summary
  lib/                shared data loading + scoring helpers
  pages/              Pages 2-6
data/
  raw/               cached raw downloads (gitignored)
  processed/         malls.csv, category_scores.csv, hpm_index.csv (committed)
```
