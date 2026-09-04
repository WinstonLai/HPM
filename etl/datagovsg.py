"""Helpers for downloading datasets from data.gov.sg's api-open Dataset API.

API pattern (verified live 2026-09-04):
  GET https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download
returns {"code":0,"data":{"url": "<time-limited S3 link>"}}. No API key is
required for this volume of one-off ETL traffic, but unauthenticated callers
are rate-limited to ~5 requests/minute, so calls are throttled and retried.

Some agency exports (e.g. HPB Gyms@SG, MOH CHAS Clinics) still carry legacy
KML-derived GeoJSON where all attributes are packed into a single
`Description` HTML table rather than clean `properties` keys;
`feature_attributes` normalises both shapes into a flat dict.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import requests

BASE_URL = "https://api-open.data.gov.sg/v1/public/api/datasets"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

MIN_SECONDS_BETWEEN_CALLS = 13.0  # keep under data.gov.sg's 5 req/min unauth limit


class DownloadError(RuntimeError):
    pass


_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _poll_download_url(dataset_id: str, retries: int = 4) -> str:
    url = f"{BASE_URL}/{dataset_id}/poll-download"
    last_err: Optional[Exception] = None
    for _ in range(retries):
        _throttle()
        resp = requests.get(url, timeout=30)
        if resp.status_code == 429:
            last_err = DownloadError(f"rate limited on {dataset_id}")
            time.sleep(20)
            continue
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise DownloadError(f"{dataset_id}: {payload.get('errorMsg')}")
        return payload["data"]["url"]
    raise last_err or DownloadError(f"failed to poll-download {dataset_id}")


def fetch_dataset(dataset_id: str, filename: str, force: bool = False) -> Path:
    """Download (or reuse cached copy of) a data.gov.sg dataset; return local path."""
    dest = RAW_DIR / filename
    if dest.exists() and not force:
        return dest
    download_url = _poll_download_url(dataset_id)
    resp = requests.get(download_url, timeout=90)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def load_geojson_features(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    return data.get("features", [])


_DESC_ROW_RE = re.compile(
    r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_kml_description(html: str) -> dict[str, str]:
    """Parse the legacy KML 'attribute table' packed into a Description field."""
    out: dict[str, str] = {}
    for key, val in _DESC_ROW_RE.findall(html or ""):
        key = _TAG_RE.sub("", key).strip()
        val = _TAG_RE.sub("", val).strip()
        if key:
            out[key] = val
    return out


def feature_attributes(feature: dict[str, Any]) -> dict[str, str]:
    """Flat attribute dict for a GeoJSON feature, handling both the clean
    `properties` format and the legacy KML/Description HTML-table format."""
    props = feature.get("properties", {}) or {}
    if "Description" in props and len(props) <= 3:
        attrs = parse_kml_description(props["Description"])
        if props.get("Name"):
            attrs.setdefault("NAME", props["Name"])
        return attrs
    return props


def feature_point(feature: dict[str, Any]) -> Optional[tuple]:
    """Return (lat, lon) for a Point-geometry feature, else None."""
    geom = feature.get("geometry") or {}
    if geom.get("type") != "Point":
        return None
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]
    return lat, lon
