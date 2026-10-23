"""Build the mall registry: scrape THREE Wikipedia sources of Singapore
shopping malls/commercial centres, union + de-duplicate them, resolve each
mall's landlord/operator from its own article infobox where one exists, and
geocode every mall via OneMap. Writes data/processed/malls.csv (and a
data/processed/registry_qa.csv audit trail of every rejection/merge).

A single hand-curated "List of..." article undercounts Singapore's shopping
malls (it only had ~90 in it), so three complementary sources are combined:
  1. List of shopping malls in Singapore   - region-organised, curated list
  2. Category:Shopping malls in Singapore  - every article Wikipedia editors
     tagged as a mall (broader than #1; automatically excludes the "Defunct
     shopping malls" subcategory since MediaWiki's categorymembers API only
     returns direct members, not recursive subcategory members)
  3. List of commercial sites in Singapore - "Housing estate commercial
     areas" section, town-by-town neighbourhood shopping centres missed by
     #1/#2 (its "Street-side areas" section is skipped: those are streets/
     precincts, not retail buildings)

Registry quality controls (each one fixes a defect found in review):
  * Geocodes are VALIDATED: OneMap's top hit is often the wrong building, so
    every candidate is checked against the mall's name (onemap.py). Malls
    with no validated hit are dropped and listed in registry_qa.csv unless
    data/manual/geocode_overrides.csv supplies a fix.
  * Duplicates are collapsed twice: before geocoding (same Wikipedia article
    after resolving redirects, or the same normalised name) and after (same
    building: shared postal code, or <=75m apart with a shared distinctive
    word in the name). Merged names are kept in the `aliases` column.
  * `mall_id` is a stable slug of the canonical article title, not a row
    index, and `postal_code` is written as a zero-padded string.
  * Operator names go through data/manual/operator_aliases.csv (merges e.g.
    "CapitaMall Trust" / "CapitaLand Mall Trust" into one landlord group and
    blanks non-landlords), and data/manual/operators.csv lets HPB CIP supply
    authoritative landlord / partnership facts per mall.

This is the "consolidate mall amenity information into a common repository...
may include culling information from publicly available sources" deliverable
from the charter's Milestone 1.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo import haversine_m  # noqa: E402
from onemap import geocode_candidates, geocode_validated, name_tokens  # noqa: E402
import validate  # noqa: E402

WIKI_API = "https://en.wikipedia.org/w/api.php"
LIST_PAGE = "List_of_shopping_malls_in_Singapore"
CATEGORY_TITLE = "Category:Shopping malls in Singapore"
COMMERCIAL_SITES_PAGE = "List_of_commercial_sites_in_Singapore"
HEADERS = {"User-Agent": "HPM-readiness-poc/1.0 (contact: hpb-cip-poc)"}
REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_DIR = REPO_ROOT / "data" / "manual"

# Post-geocode duplicate detection.
SAME_BUILDING_MAX_M = 150      # same postal code and this close => same building
NEAR_DUPLICATE_MAX_M = 75      # this close + shared name word + a missing postal => same mall

WIKI_LINK_RE = re.compile(r"^\*\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", re.MULTILINE)
# Bullet that may be a wikilink ("*[[Page|Display]]") or plain text ("*Name") -
# List of commercial sites in Singapore uses both within the same section.
BULLET_RE = re.compile(r"^\*\s*(?:\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|(\S.*))$", re.MULTILINE)
SECTION_RE = re.compile(r"^==\s*([^=]+?)\s*==\s*$", re.MULTILINE)
INFOBOX_FIELD_RE = re.compile(r"^\|\s*(owner|developer|management)\s*=\s*(.+)$", re.IGNORECASE)
WIKILINK_STRIP_RE = re.compile(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]")
REF_STRIP_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL | re.IGNORECASE)
TEMPLATE_STRIP_RE = re.compile(r"\{\{[^{}]*\}\}")
NON_MALL_SECTIONS = {"references", "see also", "notes", "external links"}
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
NAME_SUFFIX_RE = re.compile(r"\s*(?:,\s*singapore|\((?:singapore|shopping mall|mall)\))\s*$", re.IGNORECASE)
FORMER_RE = re.compile(r"\(former\)|\bformer\b", re.IGNORECASE)

# An infobox can carry all three; owner is the best proxy for "who the
# landlord is", management next, developer (who *built* it) last.
OPERATOR_FIELD_PRIORITY = ("owner", "management", "developer")

# Words that don't identify a particular mall when deciding whether two
# nearby records are the same place.
_NAME_GENERIC = {"mall", "centre", "center", "shopping", "plaza", "complex", "building",
                 "town", "square", "point", "city", "hub", "place"}


def clean_name(name: str) -> str:
    """Strip Wikipedia disambiguation noise: "Funan, Singapore" -> "Funan",
    "IMM (Singapore)" -> "IMM"."""
    return NAME_SUFFIX_RE.sub("", name or "").strip()


def dedupe_key(name: str) -> str:
    """Identity key tolerant of "The ...", ", Singapore" suffixes, punctuation
    and number words ("Lot One" == "Lot 1")."""
    return "".join(name_tokens(clean_name(name)))


def slugify(text: str) -> str:
    return NON_ALNUM_RE.sub("-", clean_name(text).lower()).strip("-")


class WikipediaError(RuntimeError):
    pass


def _wiki_get(params: dict, attempts: int = 5) -> dict:
    """GET the MediaWiki API and return parsed JSON, retrying with back-off.
    Under load the API intermittently answers with an empty/non-JSON body or
    a 429/5xx; treating that as "page has no content" silently stripped the
    operator from dozens of malls, so a persistent failure now raises."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=20)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = WikipediaError(f"HTTP {resp.status_code}")
                time.sleep(float(resp.headers.get("Retry-After", 2 * (attempt + 1))))
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise WikipediaError(f"Wikipedia API failed after {attempts} attempts: {last}")


def fetch_page(title: str) -> tuple[str, str]:
    """Return (canonical_title, wikitext) for a Wikipedia page, following
    redirects ("Funan, Singapore" and "Funan" resolve to one title). Missing
    pages give (title, "")."""
    data = _wiki_get({
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "redirects": 1,
        "format": "json",
        "formatversion": 2,
    })
    if "error" in data:  # e.g. missingtitle: plain-text entries have no article
        return title, ""
    parsed = data.get("parse", {})
    return parsed.get("title", title), parsed.get("wikitext", "")


def fetch_wikitext(title: str) -> str:
    return fetch_page(title)[1]


def scrape_regional_list() -> list[dict]:
    """Source 1: the region-organised "List of shopping malls in Singapore"."""
    wikitext = fetch_wikitext(LIST_PAGE)
    parts = SECTION_RE.split(wikitext)
    rows = []
    # parts = [preamble, heading1, body1, heading2, body2, ...]
    for i in range(1, len(parts), 2):
        region = parts[i].strip()
        body = parts[i + 1]
        if region.lower() in NON_MALL_SECTIONS:
            continue
        for page_title, display in WIKI_LINK_RE.findall(body):
            name = (display or page_title).strip()
            rows.append({"page_title": page_title.strip(), "name": name, "region": region, "source": "regional"})
    return rows


def scrape_category_members() -> list[dict]:
    """Source 2: every article directly tagged Category:Shopping malls in
    Singapore (broader than the curated list; excludes defunct malls since
    those only sit in the "Defunct shopping malls" subcategory)."""
    data = _wiki_get({
        "action": "query",
        "list": "categorymembers",
        "cmtitle": CATEGORY_TITLE,
        "cmlimit": 500,
        "cmtype": "page",
        "format": "json",
        "formatversion": 2,
    })
    members = data.get("query", {}).get("categorymembers", [])
    rows = []
    for m in members:
        title = m["title"]
        # categorymembers(cmtype=page) can still return non-article pages such
        # as "Template:Shopping malls in Singapore".
        if title.lower().startswith("list of") or ":" in title:
            continue
        rows.append({"page_title": title, "name": title, "region": "Unknown", "source": "category"})
    return rows


def scrape_commercial_estates() -> list[dict]:
    """Source 3: "Housing estate commercial areas" section of List of
    commercial sites in Singapore - neighbourhood shopping centres, some
    wikilinked and some plain text (no article exists for them yet)."""
    wikitext = fetch_wikitext(COMMERCIAL_SITES_PAGE)
    parts = SECTION_RE.split(wikitext)
    rows = []
    for i in range(1, len(parts), 2):
        section = parts[i].strip()
        body = parts[i + 1]
        if section.lower() != "housing estate commercial areas":
            continue
        for page_title, display, plain in BULLET_RE.findall(body):
            if plain:
                name = plain.strip()
                page_title = name
            else:
                name = (display or page_title).strip()
                page_title = page_title.strip()
            rows.append({"page_title": page_title, "name": name, "region": "Unknown", "source": "estate"})
    return rows


def scrape_mall_list() -> pd.DataFrame:
    """Union + de-duplicate all three sources. A row is dropped if EITHER its
    Wikipedia page title or its cleaned display name normalises to a key
    already seen, so "Seletar Mall" / "The Seletar Mall", "Funan" / "Funan,
    Singapore" and "Lot 1" / "Lot One" collapse even when linked to
    different page titles. Earlier sources win on conflicting page_title/
    region, since sources 1 and 2 are wikilinked (usable for infobox
    scraping) while source 3 is a lower-confidence supplementary list.
    Redirect-level duplicates that only show up after fetching each article
    are caught later, in build_registry."""
    all_rows = scrape_regional_list() + scrape_category_members() + scrape_commercial_estates()
    seen: set[str] = set()
    kept: list[dict] = []
    for row in all_rows:
        keys = {k for k in (dedupe_key(row["page_title"]), dedupe_key(row["name"])) if k}
        if not keys or keys & seen:
            continue
        seen |= keys
        kept.append(row)
    return pd.DataFrame(kept).reset_index(drop=True)


# --- operators -------------------------------------------------------------

def _load_manual_csv(filename: str) -> pd.DataFrame:
    path = MANUAL_DIR / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def load_operator_aliases() -> dict[str, str]:
    """raw operator text (lower-cased) -> landlord group. A blank group means
    "not a landlord" (e.g. a cinema chain, a former tenant) and becomes
    "Unknown"."""
    df = _load_manual_csv("operator_aliases.csv")
    if df.empty:
        return {}
    return {r.raw_operator.strip().lower(): r.landlord_group.strip() for r in df.itertuples()}


def clean_operator(raw: str, aliases: dict[str, str]) -> str:
    raw = (raw or "").strip()
    if not raw or raw == "Unknown" or FORMER_RE.search(raw):
        return "Unknown"
    group = aliases.get(raw.lower(), raw)
    return group or "Unknown"


def extract_operator(wikitext: str) -> str:
    """Raw landlord text from the article infobox, preferring owner over
    management over developer. Returns "Unknown" when none is present."""
    found: dict[str, str] = {}
    for line in wikitext.splitlines():
        m = INFOBOX_FIELD_RE.match(line.strip())
        if not m:
            continue
        field = m.group(1).lower()
        value = m.group(2)
        value = REF_STRIP_RE.sub("", value)
        value = TEMPLATE_STRIP_RE.sub("", value)
        value = WIKILINK_STRIP_RE.sub(r"\1", value)
        value = value.split("<br")[0].split("*")[0]
        value = value.strip(" '\"\t")
        if value and field not in found:
            found[field] = value
    for field in OPERATOR_FIELD_PRIORITY:
        if field in found:
            return found[field]
    return "Unknown"


# --- geocoding -------------------------------------------------------------

def load_geocode_overrides() -> dict[str, dict]:
    """Manual geocode fixes keyed by dedupe_key(name). A row gives either
    lat/lon directly, or a `query` to search for (top hit accepted, since a
    human has vouched for the query)."""
    df = _load_manual_csv("geocode_overrides.csv")
    return {dedupe_key(r.name): r._asdict() for r in df.itertuples(index=False)} if not df.empty else {}


def resolve_geocode(name: str, overrides: dict[str, dict]) -> tuple[dict | None, str]:
    """(geocode result or None, how it was obtained: override/validated/none)."""
    ov = overrides.get(dedupe_key(name))
    if ov:
        if ov.get("lat") and ov.get("lon"):
            postal = ov.get("postal_code", "").strip()
            return ({"lat": float(ov["lat"]), "lon": float(ov["lon"]),
                     "postal_code": postal.zfill(6) if postal else None,
                     "address": ov.get("note") or "manual override", "building": name}, "override")
        if ov.get("query"):
            cands = geocode_candidates(ov["query"])
            if cands:
                return cands[0], "override"
    return geocode_validated(clean_name(name)), "validated"


def _distinctive_tokens(name: str) -> set[str]:
    return {t for t in name_tokens(clean_name(name)) if t not in _NAME_GENERIC and len(t) > 1}


def merge_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Collapse records that describe the same mall, using the geocoded
    position. Two records are the same mall when they share a canonical
    Wikipedia article, or share a postal code within SAME_BUILDING_MAX_M, or
    sit within NEAR_DUPLICATE_MAX_M with one name's distinctive words contained
    in the other's and at least one missing postal code. Records with different postal codes
    are never merged on proximity alone (adjacent malls such as Bugis
    Junction / Bugis+ stay separate)."""
    n = len(df)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    reasons: dict[tuple[int, int], str] = {}
    lat, lon = df["lat"].to_numpy(float), df["lon"].to_numpy(float)
    # A column mixing postal strings and missing values holds NaN (which is
    # truthy!) for the missing ones, so normalise "missing" to None explicitly.
    postal = [p if isinstance(p, str) and p.strip() else None for p in df["postal_code"].tolist()]
    canon = df["canonical_title"].tolist()
    tokens = [_distinctive_tokens(nm) for nm in df["name"]]
    for i in range(n):
        dist = haversine_m(lat[i], lon[i], lat, lon)
        for j in range(i + 1, n):
            reason = None
            if canon[i] and canon[i] == canon[j]:
                reason = "same Wikipedia article"
            elif postal[i] and postal[i] == postal[j] and dist[j] <= SAME_BUILDING_MAX_M:
                reason = f"same postal code {postal[i]}"
            elif (dist[j] <= NEAR_DUPLICATE_MAX_M and not (postal[i] and postal[j]) and tokens[i] and tokens[j]
                  and (tokens[i] <= tokens[j] or tokens[j] <= tokens[i])):
                # One name's distinctive words contain the other's ("The Star" / "The Star Vista").
                # Merely sharing a place word ("Orchard Central" / "Orchard Gateway") is not enough.
                reason = f"{dist[j]:.0f}m apart, one name contains the other"
            if reason:
                reasons[(i, j)] = reason
                parent[find(j)] = find(i)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    rows, qa = [], []
    for members in groups.values():
        members.sort()  # source order: earlier = region-organised list wins
        rep = df.iloc[members[0]].to_dict()
        # Aliases already recorded on any member are kept, plus the merged names.
        known_aliases = [a for v in (df["aliases"].iloc[members] if "aliases" in df.columns else [])
                         for a in str(v if isinstance(v, str) else "").split("; ") if a]
        if "hpb_partner" in df.columns:
            rep["hpb_partner"] = int(df["hpb_partner"].iloc[members].fillna(0).astype(int).max())
        if len(members) > 1:
            others = df.iloc[members[1:]]
            rep["aliases"] = "; ".join(dict.fromkeys(known_aliases + others["name"].tolist()))
            for col in ("operator", "region", "postal_code", "address"):
                if rep.get(col) in (None, "", "Unknown") or (isinstance(rep.get(col), float) and np.isnan(rep[col])):
                    for v in df.iloc[members][col]:
                        if v not in (None, "", "Unknown") and not (isinstance(v, float) and np.isnan(v)):
                            rep[col] = v
                            break
            for other in members[1:]:
                why = next((reasons[k] for k in reasons if k[1] == other and k[0] in members), "chained duplicate")
                qa.append({"kind": "merged", "name": df.iloc[other]["name"],
                           "detail": f"merged into '{rep['name']}' ({why})"})
        else:
            rep["aliases"] = "; ".join(dict.fromkeys(known_aliases))
        rows.append(rep)
    return pd.DataFrame(rows), qa


def add_existing_hpms(df: pd.DataFrame, qa: list[dict]) -> pd.DataFrame:
    """Add every mall in data/manual/existing_hpm.csv that the Wikipedia
    sources missed. HPB's own list is better evidence that something is a
    mall than Wikipedia's categories (14 of the 48 existing HPMs were absent
    from the scraped registry: Terminal 3, United Square, KINEX, ...). New
    malls are geocoded with the same name validation as everything else; the
    operator stays "Unknown" because there is no article to read it from."""
    listed = _load_manual_csv("existing_hpm.csv")
    if listed.empty:
        return df
    known = set()
    for _, row in df.iterrows():
        known.add(dedupe_key(row["name"]))
        known.update(dedupe_key(a) for a in str(row.get("aliases") or "").split("; ") if a)
    overrides = load_geocode_overrides()
    new_rows = []
    for rec in listed.itertuples(index=False):
        display = (getattr(rec, "match_as", "") or rec.name).strip()
        if not display or dedupe_key(rec.name) in known or dedupe_key(display) in known:
            continue
        geo, how = resolve_geocode(display, overrides)
        if not geo:
            print(f"  [reject] existing HPM could not be geocoded: {display}")
            qa.append({"kind": "existing_hpm_not_geocoded", "name": display,
                       "detail": "listed in existing_hpm.csv but no OneMap candidate matched; add a geocode override"})
            continue
        print(f"  [added existing HPM] {display} -> ({geo['lat']:.4f},{geo['lon']:.4f}) [{how}]")
        qa.append({"kind": "existing_hpm_added", "name": display,
                   "detail": f"missing from the Wikipedia registry; added from existing_hpm.csv ({geo.get('building')})"})
        known.add(dedupe_key(display))
        new_rows.append({
            "mall_id": slugify(display), "name": clean_name(display), "aliases": "", "source": "existing_hpm",
            "region": "Unknown", "operator": "Unknown", "hpb_partner": 0,
            "lat": geo["lat"], "lon": geo["lon"], "postal_code": geo.get("postal_code"),
            "address": geo.get("address"),
        })
        time.sleep(0.3)
    if not new_rows:
        return df
    return pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)


MALL_TYPES = ["Shopping mall", "Neighbourhood centre", "Market / hawker centre", "Area / precinct"]
MARKET_RE = re.compile(r"\b(hawker|market|food centre|food center|food court)\b", re.IGNORECASE)
AREA_RE = re.compile(r"\b(town centre|town center|regional centre|regional center)\b", re.IGNORECASE)


def load_manual_types() -> dict[str, str]:
    """Hand-curated types from data/manual/mall_types.csv (name,type,note),
    keyed by dedupe_key(name). These beat the rules below."""
    df = _load_manual_csv("mall_types.csv")
    if df.empty:
        return {}
    bad = sorted(set(df["type"]) - set(MALL_TYPES))
    if bad:
        print(f"  [warn] mall_types.csv has unknown types {bad}; allowed: {MALL_TYPES}")
    return {dedupe_key(r.name): r.type for r in df.itertuples(index=False) if r.type in MALL_TYPES}


def classify_type(name: str, source: str, manual: dict[str, str]) -> str:
    """Best-effort type, so non-malls can be filtered out of a mall ranking.
    Order: hand-curated override; HPB-designated (always a mall); market /
    hawker keywords; "Town/Regional Centre" (an HDB town node, not a
    building); a mall that only appears in the "Housing estate commercial
    areas" list (a neighbourhood centre); otherwise a shopping mall. The
    rules are heuristics -- correct any miss in data/manual/mall_types.csv."""
    key = dedupe_key(name)
    if key in manual:
        return manual[key]
    if source == "existing_hpm":
        return "Shopping mall"
    if MARKET_RE.search(name):
        return "Market / hawker centre"
    if AREA_RE.search(name):
        return "Area / precinct"
    if source == "estate":
        return "Neighbourhood centre"
    return "Shopping mall"


def apply_types(df: pd.DataFrame) -> pd.DataFrame:
    manual = load_manual_types()
    df = df.copy()
    df["type"] = [classify_type(n, str(s), manual) for n, s in zip(df["name"], df.get("source", "category"))]
    return df


def apply_manual_operators(df: pd.DataFrame) -> pd.DataFrame:
    """Overlay data/manual/operators.csv (name, landlord_group, hpb_partner,
    source) onto the scraped operators. This is where HPB CIP's authoritative
    landlord and partnership facts go; scraped values are only the fallback."""
    df = df.copy()
    df["hpb_partner"] = 0
    manual = _load_manual_csv("operators.csv")
    if manual.empty:
        return df
    by_key = {dedupe_key(r.name): r for r in manual.itertuples(index=False)}
    for idx, row in df.iterrows():
        keys = [dedupe_key(row["name"])] + [dedupe_key(a) for a in str(row.get("aliases") or "").split("; ") if a]
        rec = next((by_key[k] for k in keys if k in by_key), None)
        if rec is None:
            continue
        if rec.landlord_group.strip():
            df.at[idx, "operator"] = rec.landlord_group.strip()
        if rec.hpb_partner.strip() in ("1", "true", "True", "yes"):
            df.at[idx, "hpb_partner"] = 1
    return df


def build_registry(limit: int | None = None, sleep_s: float = 0.3) -> pd.DataFrame:
    malls = scrape_mall_list()
    if limit:
        malls = malls.head(limit)

    aliases = load_operator_aliases()
    overrides = load_geocode_overrides()
    qa: list[dict] = []
    records = []
    seen_canonical: dict[str, str] = {}
    total = len(malls)
    for idx, row in malls.iterrows():
        page_title, name, region = row["page_title"], row["name"], row["region"]
        try:
            canonical, wikitext = fetch_page(page_title)
        except WikipediaError as exc:
            print(f"  [warn] Wikipedia fetch failed for {page_title!r}: {exc}")
            qa.append({"kind": "wiki_fetch_failed", "name": name,
                       "detail": "operator unknown because the article could not be fetched; re-run"})
            canonical, wikitext = page_title, ""
        # Two scraped titles that redirect to one article are one mall.
        ckey = dedupe_key(canonical)
        if wikitext and ckey in seen_canonical:
            qa.append({"kind": "merged", "name": name,
                       "detail": f"redirects to the same article as '{seen_canonical[ckey]}'"})
            continue

        raw_operator = extract_operator(wikitext) if wikitext else "Unknown"
        operator = clean_operator(raw_operator, aliases)

        geo, how = resolve_geocode(name, overrides)
        if not geo:
            print(f"  [reject] no validated geocode for: {name}")
            qa.append({"kind": "geocode_rejected", "name": name,
                       "detail": "no OneMap candidate matched the name; add a row to data/manual/geocode_overrides.csv"})
            continue
        if how == "override":
            qa.append({"kind": "geocode_override", "name": name, "detail": f"{geo['lat']:.5f},{geo['lon']:.5f}"})
        if wikitext:
            seen_canonical[ckey] = name

        records.append(
            {
                "mall_id": slugify(canonical if wikitext else name),
                "name": clean_name(name),
                "region": region,
                "operator": operator,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "postal_code": geo.get("postal_code"),
                "address": geo.get("address"),
                "canonical_title": canonical if wikitext else "",
                "source": row["source"],
            }
        )
        print(f"  [{idx + 1}/{total}] {name} -> operator={operator!r} "
              f"({geo['lat']:.4f},{geo['lon']:.4f}) [{how}]")
        time.sleep(sleep_s)

    df, merge_qa = merge_duplicates(pd.DataFrame(records))
    qa.extend(merge_qa)
    print(f"\nMerged {len(merge_qa)} duplicate records; rejected "
          f"{sum(1 for q in qa if q['kind'] == 'geocode_rejected')} unverifiable geocodes.")

    df = apply_manual_operators(df)
    df = add_existing_hpms(df, qa)
    df = apply_types(df)
    # Stable, unique ids (a slug collision gets a numeric suffix).
    counts: dict[str, int] = {}
    ids = []
    for mid in df["mall_id"]:
        counts[mid] = counts.get(mid, 0) + 1
        ids.append(mid if counts[mid] == 1 else f"{mid}-{counts[mid]}")
    df["mall_id"] = ids
    df["postal_code"] = df["postal_code"].astype("string")

    validate.enforce("registry", *validate.validate_registry(df))
    pd.DataFrame(qa, columns=["kind", "name", "detail"]).to_csv(PROCESSED_DIR / "registry_qa.csv", index=False)
    return df[["mall_id", "name", "aliases", "type", "region", "operator", "hpb_partner",
               "lat", "lon", "postal_code", "address"]].reset_index(drop=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only process first N malls (debug)")
    parser.add_argument("--dedupe", action="store_true",
                        help="don't re-geocode: merge duplicate malls in the current malls.csv "
                             "(same postal code, or nearly the same spot with one name containing the other)")
    parser.add_argument("--refresh-types", action="store_true",
                        help="don't re-geocode: recompute the `type` column of the current malls.csv "
                             "(re-reads the three Wikipedia lists to see where each mall came from)")
    parser.add_argument("--add-existing-hpms", action="store_true",
                        help="don't re-scrape: add malls from data/manual/existing_hpm.csv that "
                             "are missing from the current malls.csv, and exit")
    args = parser.parse_args()

    if args.limit:   # a partial registry must not replace the committed one
        import provenance
        out = provenance.redirect_processed_dir(provenance.SCRATCH_DIR, sys.modules[__name__])
        print(f"--limit run: writing to {out} (not data/processed/)")

    if args.dedupe:
        current = pd.read_csv(PROCESSED_DIR / "malls.csv", dtype={"postal_code": str})
        current["aliases"] = current["aliases"].fillna("")
        current["canonical_title"] = ""
        merged, qa_new = merge_duplicates(current)
        merged = merged.drop(columns=["canonical_title"])
        merged["postal_code"] = merged["postal_code"].astype("string")
        merged.to_csv(PROCESSED_DIR / "malls.csv", index=False)
        qa_path = PROCESSED_DIR / "registry_qa.csv"
        qa_old = pd.read_csv(qa_path) if qa_path.exists() else pd.DataFrame(columns=["kind", "name", "detail"])
        pd.concat([qa_old, pd.DataFrame(qa_new, columns=["kind", "name", "detail"])]).to_csv(qa_path, index=False)
        for q in qa_new:
            print(f"  merged {q['name']}: {q['detail']}")
        print(f"\n{len(current)} -> {len(merged)} malls")
        raise SystemExit(0)

    if args.refresh_types:
        current = pd.read_csv(PROCESSED_DIR / "malls.csv", dtype={"postal_code": str})
        current["aliases"] = current["aliases"].fillna("")
        origin: dict[str, str] = {}
        for rec in scrape_mall_list().itertuples():
            for k in (dedupe_key(rec.page_title), dedupe_key(rec.name)):
                origin.setdefault(k, rec.source)
        hpm = _load_manual_csv("existing_hpm.csv")
        hpm_keys = {dedupe_key(n) for col in ("name", "match_as") if col in hpm for n in hpm[col] if n}

        def source_of(row) -> str:
            keys = [dedupe_key(row["name"])] + [dedupe_key(a) for a in str(row["aliases"]).split("; ") if a]
            if any(k in hpm_keys for k in keys):
                return "existing_hpm"
            return next((origin[k] for k in keys if k in origin), "category")

        current["source"] = current.apply(source_of, axis=1)
        current = apply_types(current).drop(columns=["source"])
        cols = ["mall_id", "name", "aliases", "type"] + [c for c in current.columns
                                                         if c not in ("mall_id", "name", "aliases", "type")]
        current[cols].to_csv(PROCESSED_DIR / "malls.csv", index=False)
        print(current["type"].value_counts().to_string())
        raise SystemExit(0)

    if args.add_existing_hpms:
        current = pd.read_csv(PROCESSED_DIR / "malls.csv", dtype={"postal_code": str})
        current["aliases"] = current["aliases"].fillna("")
        qa_new: list[dict] = []
        if "type" in current.columns:
            current["source"] = current["type"].map(lambda t: "estate" if t == "Neighbourhood centre" else "category")
        updated = add_existing_hpms(current, qa_new)
        if "type" in updated.columns:
            updated["type"] = updated["type"].fillna("Shopping mall")
        updated = updated.drop(columns=["source"], errors="ignore")
        counts: dict[str, int] = {}
        ids = []
        for mid in updated["mall_id"]:
            counts[mid] = counts.get(mid, 0) + 1
            ids.append(mid if counts[mid] == 1 else f"{mid}-{counts[mid]}")
        updated["mall_id"] = ids
        updated.to_csv(PROCESSED_DIR / "malls.csv", index=False)
        qa_path = PROCESSED_DIR / "registry_qa.csv"
        qa_old = pd.read_csv(qa_path) if qa_path.exists() else pd.DataFrame(columns=["kind", "name", "detail"])
        qa_old = qa_old[~qa_old["kind"].isin(["existing_hpm_added", "existing_hpm_not_geocoded"])]
        pd.concat([qa_old, pd.DataFrame(qa_new, columns=["kind", "name", "detail"])]).to_csv(qa_path, index=False)
        print(f"\nAdded {len(updated) - len(current)} malls; registry now has {len(updated)}.")
        raise SystemExit(0)

    df = build_registry(limit=args.limit)
    out_path = PROCESSED_DIR / "malls.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} malls to {out_path}")
