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
7. **Methodology** — plain-language explanation of the data sources, why raw counts are normalised, and the category weights, with an interactive worked example that recomputes any selected mall's actual score step by step (Supply contributions → Demand contributions → final index), a "what this score doesn't capture" section, and a robustness section (alternative readings of the charter's weights, rank stability under random re-weighting, nominal vs effective weights).
8. **Regional Priorities** — high-demand malls by region or planning area that HPB has not yet reached, chain-vs-independent landlord comparison, and a backtest of the index against HPB's existing Health Promoting Malls (once `data/manual/existing_hpm.csv` is supplied).

## Data sources

Every category is backed by at least one real, freely downloadable government
dataset — no scraping of anything other than Wikipedia and no data was
fabricated. All data.gov.sg datasets are pulled live via the current
`api-open.data.gov.sg` download API.

| Category | Datasets | Publisher |
|---|---|---|
| Mall registry | Three Wikipedia sources unioned + de-duplicated: "List of shopping malls in Singapore", `Category:Shopping malls in Singapore`, and the "Housing estate commercial areas" section of "List of commercial sites in Singapore" (173 malls after de-duplication and geocode validation) — geocoded via OneMap Search API | Wikipedia / OneMap (SLA) |
| A – Healthy Dining | Healthier Eateries, Healthier Dining Partners – F&B Partners, List of Supermarket Licences | HPB / NEA |
| B – Physical Activity | Gyms@SG, SportSG Sport Facilities, commercial gyms and studios from OpenStreetMap (Overpass API) | HPB / SportSG / OpenStreetMap contributors |
| C – H365 & HPB Engagement | Community Club / PAssion WaVe Outlet (proxy — see Limitations) | People's Association |
| D – Healthcare | CHAS Clinics, Listing of Licensed Pharmacies | MOH / HSA |
| E – Healthy Infrastructure | Parks@SG, Park Facilities (playgrounds, fitness areas, drinking fountains, foot-relax), LTA Bicycle Rack | HPB / NParks / LTA |
| F – Landlord & Partnership Readiness | Operator scraped from Wikipedia infobox (proxy — see Limitations) | Wikipedia |
| G – Demand (Reach/Population/Accessibility) | Resident Population by Planning Area/Subzone (Census 2020), Master Plan 2019 Subzone Boundary, LTA MRT Station Exits, LTA Bus Stops | SingStat / URA / LTA |

Exact dataset IDs are in `etl/build_amenities.py`.

## Methodology

- **Mall registry quality controls**: OneMap's top search hit is frequently
  the wrong building (it ranks a Taman Jurong clinic above Jurong Point, a
  primary school above White Sands, Nexus International School above NEX),
  so every candidate is checked against the mall's name and only a matching
  one is accepted; malls with no match are dropped and listed in
  `data/processed/registry_qa.csv` unless `data/manual/geocode_overrides.csv`
  supplies a fix. Duplicates (the same article under two titles, "The X" vs
  "X", the same building geocoded twice) are merged and the other names kept
  in the `aliases` column. `mall_id` is a stable slug and `postal_code` a
  zero-padded string.
- **Matching amenities to malls**: datasets with a clean building-name field
  (e.g. `ADDRESSBUILDINGNAME`, `BUILDING_NAME`) are matched by normalised
  name equality — accepted only within 500m of the mall, and skipped for
  names shared by several malls (e.g. "Rivervale Plaza"/"Rivervale Mall");
  name matches rejected for distance are written to
  `data/processed/matching_qa.csv` as a bad-geocode signal. Everything is
  additionally matched by straight-line
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
- **Normalisation**: every raw count is capped at the 95th percentile and then
  min-max scaled to 0–100 across the mall population (`geo.min_max_normalize`,
  `WINSOR_QUANTILE`), so a mall's score reflects its *relative* standing, not
  its raw size. This is **not** the charter's own worked example (which
  divides by each mall's *total* tenant count, e.g. "% of F&B outlets in
  HDP") — that formula needs a full per-mall tenant directory, which is not
  publicly available. Min-max scaling is a linear rescale of the raw count:
  it puts categories on a common 0–100 scale so they can be weighted and
  summed, but within a category the ranking is the same as the raw-count
  ranking, so it does **not** remove the size bias the charter warns about.
  The cap addresses outlier sensitivity: without it one mall with a very
  high count compressed everyone else's score, and categories' *effective*
  influence (weight × spread) drifted far from their nominal weight (e.g.
  Fitness 19.6% vs a nominal 25%); with it they are within a few points. The
  top ~5% of malls in each category now tie at 100.
- **On-site amenities go to the nearest mall only**: dining, fitness, healthcare
  and bicycle-rack points within 200m of a mall count for their *nearest* mall
  (`count_nearby(..., exclusive=True)`), so a cluster such as Orchard or Bugis
  doesn't count one eatery for several malls. Parks and community clubs
  (500m) and the demand-side catchments remain shared.
- **Region assignment**: every mall's `region` is the URA region of its
  *nearest* Master Plan subzone centroid (Central/East/North/North-East/
  West), computed after geocoding — not the region label from whichever
  Wikipedia source it came from (most of the malls, sourced from the
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
  plus a +20 bonus for the one confirmed partnership. The infobox
  field used is owner, else management, else developer. Known variants of
  one landlord are merged by hand in `data/manual/operator_aliases.csv`
  (e.g. all the CapitaLand trust names → "CapitaLand"), and
  `data/manual/operators.csv` lets HPB CIP supply authoritative landlord
  and `hpb_partner` facts per mall, which override the scraped values.
  Operator names not in the alias table are still free text and may not
  merge.
- **Category A "% of F&B outlets in HDP"**: no public per-mall total-tenant-
  count dataset exists, so Category A is a density score (HDP outlets +
  Healthier Dining Partners + licensed supermarkets found near the mall),
  not a true participation percentage. Supermarket *presence* is included
  (NEA's List of Supermarket Licences), but there's no public dataset that
  flags which specific supermarkets carry HPB's "healthier choice" range —
  so this counts any licensed supermarket, not specifically ones "with
  healthier choice options" as the charter's measure names it.
- **Population catchment**: Reach & Population = 50% residents + 30% seniors
  (65+) + 20% workers, each capped and scaled. People are counted by
  distance: a subzone (Census 2020, placed at its polygon *centroid*, a
  simple vertex-average) counts fully at the mall and fades linearly to 0 at
  2km (`REACH_KERNEL_RADIUS_M`), replacing a hard 1.2km circle that made a
  subzone vanish just across the line. Workers are *employed residents by
  planning area of workplace* (Census 2020, data.gov.sg), spread over each
  area's subzones by land area — a coarse daytime signal that excludes
  foreign workers and visitors. `daytime_led` flags malls whose weighted
  catchment holds more workers than residents. The Engagement Gap still uses
  the hard 1.2km resident circle (`pop_catchment`) to match its amenity
  counts. Accessibility = 50% MRT + 50% bus: MRT counts each *station* once
  (the LTA file has one row per exit, so an interchange used to look like
  many stations) with distance decay to 1.2km, and bus stops decay to 400m;
  bus *services* are not available.
- **Category E (Healthy Infrastructure)**: NParks' Park Facilities dataset
  lists every piece of park infrastructure (mostly carparks, noticeboards,
  access points and map boards). Only `PLAYGROUND`, `FITNESS AREA`,
  `DRINKING FOUNTAIN` (the charter's water refill points) and `FOOT RELAX`
  (wellness) rows are counted (`PARK_FACILITY_CLASSES` in
  `build_category_scores.py`); Parks@SG parks and LTA bicycle racks are
  unchanged. These are park facilities within 500m, not facilities inside
  the mall.
- **Category B (Physical Activity)**: Gyms@SG only lists HPB-registered
  gyms, so commercial gyms and fitness studios are added from OpenStreetMap
  (`etl/osm.py`, Overpass API; `leisure=fitness_centre|sports_centre`,
  `amenity=gym`). OSM venues within 40m of a listed venue are dropped as
  duplicates. OSM coverage of small studios is patchy.
- **"% of F&B outlets" (experiment, not in the index)**: the charter's
  normalised Healthy Dining metric needs a per-mall tenant count. As a
  trial, `A_healthier_share` = HPB healthier-eatery outlets ÷ OSM F&B
  outlets within 200m (malls with ≥5 mapped F&B outlets). It stays out of
  the score because OSM is incomplete inside malls (in 11 malls HPB lists
  more healthier outlets than OSM maps F&B outlets at all) and it tracks the
  raw count closely (rank correlation ~0.8). A real tenant directory would
  make it usable.
- **Existing HPMs**: `data/manual/existing_hpm.csv` (`name,source,match_as`)
  holds the 48 malls HPB CIP lists as existing Health Promoting Malls
  (`match_as` is the registry spelling where HPB's differs, e.g. "Singpost
  Centre" → "SingPost"). The build sets `is_existing_hpm` from it, and the
  Regional Priorities page backtests the index. **14 of the 48 were missing
  from the Wikipedia-scraped registry** (Terminal 3, United Square, KINEX,
  Paya Lebar Quarter, ...), plus Velocity @ Novena Square, so the registry
  build now adds any listed mall it lacks
  (`build_mall_registry.add_existing_hpms`; `--add-existing-hpms` does just
  that without re-scraping). The same gap probably affects malls that are
  not on the list, so the registry should be treated as incomplete.
  Result at the time of writing: AUC 0.73 (0.5 = chance); 13 of 48 existing
  HPMs rank in the Top 20 and 25 in the Top 50 of 188. Healthy Dining
  separates them best (0.77) but is partly circular, since it is built from
  HPB's own Healthier Dining datasets; Accessibility (0.48) and Physical
  Activity (0.52) do not separate them at all.
- **Robustness**: `scoring_formula.rank_stability` re-ranks the malls under 500
  random weightings, and `scenario_comparison` compares other readings of
  the charter's ambiguous weights (its category weights sum to 90 + Demand
  10, yet it also says 70/30). The default is unchanged; the interpretation
  still needs HPB CIP's sign-off.
- **Category A overlap**: the Healthier Eateries and Healthier Dining
  Partners datasets describe many of the same outlets. Partner outlets are
  dropped when an eatery with the same postal code + brand exists, and
  verbatim-repeated partner rows are collapsed. Outlets with no parseable
  postal code or a differently spelled brand can still be double-counted.
- **Category F coverage**: a landlord was found for about half the malls
  (89 of 173 at the time of writing); the rest are "Unknown" and count as a
  portfolio of one, so Category F is still non-zero for only 30 malls. (An
  earlier build found just 24: Wikipedia fetches that failed under load were
  silently treated as "no infobox". They now retry, and a persistent failure
  is recorded in `registry_qa.csv`.)
- **Tiers and quadrants** are relative: tiers are quartiles of the rank
  (top quarter = Platinum … bottom quarter = Bronze); quadrants split Supply
  and Demand at their medians.
- **Engagement Gap** ("untapped demand"): health-promoting amenities
  (healthier eateries, gyms/sport facilities, CHAS clinics) within 1.2km,
  compared with the number a catchment of that population would typically
  have (a fitted `log(amenities) = a + b·log(population)` trend across all
  malls). Malls are rank-scaled on the shortfall — biggest shortfall = 100 —
  because the residuals are heavy-tailed. A plain amenities-per-resident
  ratio was tried first, but it correlated ~0.8 with Reach & Population, so
  population counted twice in the Demand block; the residual is uncorrelated
  with population by construction. A mall with no residents in its catchment
  has no meaningful gap: the score is NaN ("n/a") and `scoring_formula`
  re-weights that mall's Demand score over its other factors rather than
  scoring it 0. Community Clubs are deliberately excluded so the factor
  doesn't simply mirror Category C (an earlier version defined it as
  `100 - Category C`, which cancelled C's own Supply contribution almost
  exactly).
- **Default weights**: the charter's illustrative Supply weights
  (25/20/15/10/10/10, summing to 90 because Demand Potential was 10) are
  re-scaled to sum to 100 within the Supply block, except that the two
  proxy categories start lower (H365 & HPB Engagement 15 → 10, Partnership
  Readiness 10 → 5) because they are coarse stand-ins; the charter values
  are kept as `CHARTER_SUPPLY_WEIGHTS` in `etl/scoring_formula.py`, and the
  What-If Simulator can switch both proxies off. The Demand block's three
  factors are weighted equally (the charter doesn't specify them).

## Repository layout

```
etl/                ETL pipeline (run_all.py orchestrates everything)
  datagovsg.py       data.gov.sg download client (throttled/retried)
  onemap.py          OneMap Search API geocoding
  geo.py             haversine distance, polygon centroid, capped min-max scaling
  osm.py             OpenStreetMap (Overpass) extracts: commercial fitness venues, F&B outlets
  scoring_formula.py single source of truth for the composite index formula
  build_mall_registry.py   Wikipedia scrape + geocoding -> malls.csv
  build_amenities.py       downloads all raw datasets -> data/raw/
  build_category_scores.py joins + normalises -> category_scores.csv
  build_index.py           applies default weights -> hpm_index.csv
app/                 Streamlit dashboard
  Home.py            Page 1 - Executive Summary
  lib/                shared data loading + scoring helpers
  pages/              Pages 2-8
data/
  raw/               cached raw downloads (gitignored)
  manual/            hand-maintained inputs: geocode_overrides.csv, operator_aliases.csv, operators.csv
  processed/         malls.csv, category_scores.csv, hpm_index.csv, plus registry_qa.csv /
                     matching_qa.csv audit trails (committed)
```
