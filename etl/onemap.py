"""Geocoding via OneMap's public Search API.

Verified live: GET https://www.onemap.gov.sg/api/common/elastic/search
returns usable LATITUDE/LONGITUDE/POSTAL results for an unauthenticated
caller (it includes an "Authentication token missing" notice but still
returns full results) -- no OneMap account/API key needed for this POC's
one-off geocoding volume.

OneMap's *first* hit is frequently the wrong building (searching "Jurong
Point" ranks a Taman Jurong clinic above the mall; "White Sands" ranks a
primary school; "Nex" ranks Nexus International School). So callers should
use `geocode_validated`, which walks every candidate and only accepts one
whose BUILDING text actually matches the mall's name.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests

SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"

# OneMap has no documented per-caller rate limit, but a mall with no primary
# match can trigger a fallback query plus retries -- up to 4 real requests
# behind what build_mall_registry.py budgets as a single 0.3s-apart call.
# Throttle at the request level (not just per-mall) so that fan-out can't
# push the effective rate far past what was tuned.
MIN_SECONDS_BETWEEN_CALLS = 0.25
_last_call = 0.0

# Rough Singapore bounding box; anything outside is a bad hit.
SG_LAT_RANGE = (1.15, 1.48)
SG_LON_RANGE = (103.6, 104.1)


def _throttle() -> None:
    global _last_call
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _to_result(raw: dict) -> Optional[dict]:
    try:
        lat, lon = float(raw["LATITUDE"]), float(raw["LONGITUDE"])
    except (KeyError, ValueError, TypeError):
        return None
    if not (SG_LAT_RANGE[0] <= lat <= SG_LAT_RANGE[1] and SG_LON_RANGE[0] <= lon <= SG_LON_RANGE[1]):
        return None
    postal = raw.get("POSTAL")
    return {
        "lat": lat,
        "lon": lon,
        "postal_code": None if postal in (None, "", "NIL") else str(postal).zfill(6),
        "address": raw.get("ADDRESS"),
        "building": raw.get("BUILDING"),
    }


def geocode_candidates(query: str, attempts: int = 3) -> list[dict]:
    """Return every OneMap result for `query` (best-ranked first). OneMap
    occasionally returns an empty/non-JSON body under load, so a failed
    attempt is retried after a short back-off."""
    for attempt in range(attempts):
        _throttle()
        try:
            resp = requests.get(
                SEARCH_URL,
                params={
                    "searchVal": query,
                    "returnGeom": "Y",
                    "getAddrDetails": "Y",
                    "pageNum": 1,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError):
            time.sleep(1.0 * (attempt + 1))
            continue
        results = [_to_result(r) for r in (payload.get("results") or [])]
        return [r for r in results if r]
    return []


def geocode(query: str) -> Optional[dict]:
    """Return the top-ranked OneMap result for `query` with NO validation."""
    candidates = geocode_candidates(query)
    return candidates[0] if candidates else None


def geocode_with_retry(query: str, attempts: int = 2, delay: float = 0.5) -> Optional[dict]:
    for i in range(attempts):
        result = geocode(query)
        if result:
            return result
        if i < attempts - 1:
            time.sleep(delay)
    return None


# --- candidate validation ------------------------------------------------

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                 "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
# Dropped when comparing names: never distinguishes one mall from another.
_NOISE_TOKENS = {"the", "singapore"}
# Generic words that follow a mall's distinctive name. Dropped only in the
# loosest tier, and never allowed to leave a lone token behind ("Rivervale
# Plaza" must not be accepted as "Rivervale Mall").
_GENERIC_TOKENS = {"mall", "centre", "center", "shopping", "plaza", "complex", "building", "town"}


# Words that mean the building is something other than a mall that merely shares
# its name ("WHITE SANDS PRIMARY SCHOOL", "... TOWN COUNCIL (SERVICE CENTRE)").
_NOT_A_MALL = {
    "school", "primary", "secondary", "college", "university", "institute", "academy", "kindergarten",
    "preschool", "childcare", "nursery", "tuition", "hospital", "clinic", "polyclinic", "dental", "medical",
    "surgery", "church", "temple", "mosque", "mrt", "lrt", "station", "exit", "carpark", "council",
    "police", "cemetery", "pte", "ltd",
}


def name_tokens(name: str) -> list[str]:
    toks = _NON_ALNUM_RE.sub(" ", (name or "").lower()).split()
    return [_NUMBER_WORDS.get(t, t) for t in toks if t not in _NOISE_TOKENS]


def _contains_phrase(haystack: list[str], needle: list[str]) -> Optional[int]:
    """Index at which `needle` occurs contiguously in `haystack`, else None."""
    n = len(needle)
    if n == 0:
        return None
    for i in range(len(haystack) - n + 1):
        if haystack[i:i + n] == needle:
            return i
    return None


def match_score(mall_name: str, candidate: dict) -> int:
    """How well a OneMap candidate's BUILDING text matches the mall name.
    3 = same words (optionally ignoring "shopping"); 2 = the mall's full name
    ends the building text (a tenant inside the mall geocodes to the mall) or
    starts it with a harmless qualifier ("GREAT WORLD CITY"); 1 = same distinctive words once generic suffixes
    ("Centre"/"Plaza"/...) are dropped, requiring 2+ distinctive words;
    0 = no match."""
    want = name_tokens(mall_name)
    have = name_tokens(candidate.get("building") or "")
    if not want or not have:
        return 0
    if want == have:
        return 3
    strip = lambda toks: [t for t in toks if t != "shopping"]  # noqa: E731
    if strip(want) == strip(have):
        return 3
    # The mall's name inside the building text. Either it ENDS the text -- a
    # tenant ("GOLDEN VILLAGE (GV SUNTEC CITY)", "VELOCITY @ NOVENA SQUARE") --
    # or it STARTS it with a qualifier after ("GREAT WORLD CITY", "ZHUJIAO
    # CENTRE (TEKKA MARKET)", "NORTHSHORE PLAZA I"). A qualifier that names an
    # institution ("WHITE SANDS PRIMARY SCHOOL") is a different building that
    # shares a word, often over a kilometre away, so it is rejected.
    pos = _contains_phrase(have, want)
    if pos is not None:
        ends = pos + len(want) == len(have)
        starts = pos == 0
        rest = set(have[:pos] + have[pos + len(want):])
        if ends or (starts and not rest & _NOT_A_MALL):
            return 2
    # Loosest tier: ignore only *trailing* generic words, so "Cheng San
    # Centre" ~ "Cheng San Shopping Centre" but "Tampines 1" does not match
    # "Tampines Plaza 1" and "Hougang Town Centre" does not match a town
    # council office.
    want_core, have_core = _strip_trailing_generic(strip(want)), _strip_trailing_generic(strip(have))
    if len(want_core) >= 2 and want_core == have_core:
        return 1
    return 0


def _strip_trailing_generic(toks: list[str]) -> list[str]:
    toks = list(toks)
    while toks and toks[-1] in _GENERIC_TOKENS:
        toks.pop()
    return toks


def best_candidate(mall_name: str, candidates: list[dict]) -> Optional[dict]:
    """Highest-scoring candidate that actually matches `mall_name`; ties go
    to the better-ranked hit, preferring ones that carry a postal code."""
    best, best_key = None, (0, 0, 0)
    for rank, cand in enumerate(candidates):
        score = match_score(mall_name, cand)
        if score == 0:
            continue
        key = (score, 1 if cand.get("postal_code") else 0, -rank)
        if key > best_key:
            best, best_key = cand, key
    return best


_DIGIT_WORDS = {v: k for k, v in _NUMBER_WORDS.items()}


def _number_variants(name: str) -> list[str]:
    """OneMap indexes "Lot One" but not "Lot 1" (and vice versa), so also try
    the name with numbers spelled out / written as digits."""
    words = name.split()
    swapped = [(_DIGIT_WORDS.get(w, _NUMBER_WORDS.get(w.lower(), w))) for w in words]
    variant = " ".join(swapped)
    return [variant] if variant != " ".join(words) else []


def geocode_validated(mall_name: str, extra_queries: tuple[str, ...] = ()) -> Optional[dict]:
    """Geocode `mall_name`, accepting only a candidate whose building text
    matches the name. Tries the bare name first, then name + common suffixes.
    Returns None when nothing validates (caller decides what to do)."""
    queries = [mall_name, *extra_queries, *_number_variants(mall_name), f"{mall_name} Singapore",
               f"{mall_name} Shopping Centre", f"{mall_name} Mall"]
    seen = set()
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        hit = best_candidate(mall_name, geocode_candidates(q))
        if hit:
            return hit
    return None
