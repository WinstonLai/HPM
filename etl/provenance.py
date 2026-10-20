"""Provenance for the processed data: when it was built, from which raw files
and with which parameters, written to data/processed/_meta.json.

Every stage calls `update_meta(section, info)`, which merges its section into
the file, so the dashboard (and a reviewer) can tell how old the data is and
exactly what went into it -- the raw downloads are gitignored, so without this
there is no record of which vintage of each dataset produced the committed CSVs.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
META_PATH = PROCESSED_DIR / "_meta.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _row_count(path: Path) -> int | None:
    try:
        if path.suffix == ".geojson":
            return len(json.loads(path.read_text()).get("features", []))
        if path.suffix == ".csv":
            with path.open() as fh:
                return max(sum(1 for _ in fh) - 1, 0)
    except (OSError, ValueError):
        return None
    return None


def raw_inventory() -> dict:
    """Size, row count, SHA-256 and download time of every cached raw file."""
    files: dict[str, dict] = {}
    latest = 0.0
    if RAW_DIR.exists():
        for path in sorted(RAW_DIR.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            st = path.stat()
            latest = max(latest, st.st_mtime)
            files[path.name] = {
                "bytes": st.st_size,
                "rows": _row_count(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
                "fetched": datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
            }
    return {
        "latest_fetch": datetime.fromtimestamp(latest, timezone.utc).replace(microsecond=0).isoformat() if latest else "",
        "files": files,
    }


def update_meta(section: str, info: dict) -> None:
    """Merge `info` into `section` of _meta.json (creating the file if needed)."""
    meta: dict = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
        except (OSError, ValueError):
            meta = {}
    meta[section] = {"built_at": now_iso(), "git_commit": git_commit(), **info}
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True, default=str) + "\n")
