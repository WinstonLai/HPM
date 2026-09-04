"""Geocoding via OneMap's public Search API.

Verified live: GET https://www.onemap.gov.sg/api/common/elastic/search
returns usable LATITUDE/LONGITUDE/POSTAL results for an unauthenticated
caller (it includes an "Authentication token missing" notice but still
returns full results) -- no OneMap account/API key needed for this POC's
one-off geocoding volume.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"


def geocode(query: str) -> Optional[dict]:
    """Return the best-matching OneMap result for `query`, or None."""
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
    except requests.RequestException:
        return None

    results = payload.get("results") or []
    if not results:
        return None
    top = results[0]
    try:
        return {
            "lat": float(top["LATITUDE"]),
            "lon": float(top["LONGITUDE"]),
            "postal_code": None if top.get("POSTAL") in (None, "NIL") else top.get("POSTAL"),
            "address": top.get("ADDRESS"),
            "building": top.get("BUILDING"),
        }
    except (KeyError, ValueError, TypeError):
        return None


def geocode_with_retry(query: str, attempts: int = 2, delay: float = 0.5) -> Optional[dict]:
    for i in range(attempts):
        result = geocode(query)
        if result:
            return result
        if i < attempts - 1:
            time.sleep(delay)
    return None
