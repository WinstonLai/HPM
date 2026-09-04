"""Build the mall registry: scrape THREE Wikipedia sources of Singapore
shopping malls/commercial centres, union + de-duplicate them, resolve each
mall's landlord/operator from its own article infobox where one exists, and
geocode every mall via OneMap. Writes data/processed/malls.csv.

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

This is the "consolidate mall amenity information into a common repository...
may include culling information from publicly available sources" deliverable
from the charter's Milestone 1.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onemap import geocode_with_retry  # noqa: E402

WIKI_API = "https://en.wikipedia.org/w/api.php"
LIST_PAGE = "List_of_shopping_malls_in_Singapore"
CATEGORY_TITLE = "Category:Shopping malls in Singapore"
COMMERCIAL_SITES_PAGE = "List_of_commercial_sites_in_Singapore"
HEADERS = {"User-Agent": "HPM-readiness-poc/1.0 (contact: hpb-cip-poc)"}
PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

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


def dedupe_key(name: str) -> str:
    return NON_ALNUM_RE.sub("", name.lower())


def fetch_wikitext(title: str) -> str:
    resp = requests.get(
        WIKI_API,
        params={
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": 2,
        },
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        return ""
    return data.get("parse", {}).get("wikitext", "")


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
            rows.append({"page_title": page_title.strip(), "name": name, "region": region})
    return rows


def scrape_category_members() -> list[dict]:
    """Source 2: every article directly tagged Category:Shopping malls in
    Singapore (broader than the curated list; excludes defunct malls since
    those only sit in the "Defunct shopping malls" subcategory)."""
    resp = requests.get(
        WIKI_API,
        params={
            "action": "query",
            "list": "categorymembers",
            "cmtitle": CATEGORY_TITLE,
            "cmlimit": 500,
            "cmtype": "page",
            "format": "json",
            "formatversion": 2,
        },
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    members = resp.json().get("query", {}).get("categorymembers", [])
    rows = []
    for m in members:
        title = m["title"]
        if title.lower().startswith("list of"):
            continue
        rows.append({"page_title": title, "name": title, "region": "Unknown"})
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
            rows.append({"page_title": page_title, "name": name, "region": "Unknown"})
    return rows


def scrape_mall_list() -> pd.DataFrame:
    """Union + de-duplicate all three sources (by normalised display name,
    so e.g. a wikilinked and plain-text mention of the same mall collapse
    into one row). Earlier sources win on conflicting page_title/region,
    since sources 1 and 2 are wikilinked (usable for infobox scraping) while
    source 3 is a lower-confidence supplementary list."""
    all_rows = scrape_regional_list() + scrape_category_members() + scrape_commercial_estates()
    seen: dict[str, dict] = {}
    for row in all_rows:
        key = dedupe_key(row["name"])
        if key and key not in seen:
            seen[key] = row
    df = pd.DataFrame(seen.values()).reset_index(drop=True)
    return df


def extract_operator(wikitext: str) -> str:
    for line in wikitext.splitlines():
        m = INFOBOX_FIELD_RE.match(line.strip())
        if not m:
            continue
        value = m.group(2)
        value = REF_STRIP_RE.sub("", value)
        value = TEMPLATE_STRIP_RE.sub("", value)
        value = WIKILINK_STRIP_RE.sub(r"\1", value)
        value = value.split("<br")[0].split("*")[0]
        value = value.strip(" '\"\t")
        if value:
            return value
    return "Unknown"


def build_registry(limit: int | None = None, sleep_s: float = 0.3) -> pd.DataFrame:
    malls = scrape_mall_list()
    if limit:
        malls = malls.head(limit)

    records = []
    total = len(malls)
    for idx, row in malls.iterrows():
        page_title, name, region = row["page_title"], row["name"], row["region"]
        try:
            wikitext = fetch_wikitext(page_title)
        except requests.RequestException:
            wikitext = ""
        operator = extract_operator(wikitext) if wikitext else "Unknown"

        geo = geocode_with_retry(name) or geocode_with_retry(f"{name} Singapore")
        if not geo:
            print(f"  [warn] could not geocode: {name}")
            continue

        records.append(
            {
                "mall_id": idx,
                "name": name,
                "region": region,
                "operator": operator,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "postal_code": geo.get("postal_code"),
                "address": geo.get("address"),
            }
        )
        print(f"  [{idx + 1}/{total}] {name} -> operator={operator!r} "
              f"({geo['lat']:.4f},{geo['lon']:.4f})")
        time.sleep(sleep_s)

    return pd.DataFrame(records)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only process first N malls (debug)")
    args = parser.parse_args()

    df = build_registry(limit=args.limit)
    out_path = PROCESSED_DIR / "malls.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} malls to {out_path}")
