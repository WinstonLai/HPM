"""User-Agent for the ETL's HTTP requests. Wikimedia and Overpass ask API clients to identify
themselves with a way to reach the operator; set HPM_CONTACT (an email or URL) to add yours,
otherwise the project's repository URL is sent."""
from __future__ import annotations

import os

PROJECT_URL = "https://github.com/WinstonLai/HPM"


def user_agent() -> str:
    contact = os.environ.get("HPM_CONTACT", "").strip()
    return f"HPM-readiness-poc/1.0 (+{PROJECT_URL}{'; ' + contact if contact else ''})"
