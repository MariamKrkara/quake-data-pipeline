"""Extract: pull GeoJSON features from the USGS FDSN event REST API."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings

log = logging.getLogger(__name__)


def build_session() -> requests.Session:
    """HTTP session that retries transient failures with exponential backoff."""
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "quake-data-pipeline/1.0"
    return session


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def fetch_events(
    settings: Settings,
    starttime: datetime,
    updated_after: datetime | None = None,
    session: requests.Session | None = None,
) -> list[dict]:
    """Return all features matching the window, following offset pagination."""
    session = session or build_session()
    features: list[dict] = []
    offset = 1  # the USGS API is 1-indexed

    while True:
        params = {
            "format": "geojson",
            "starttime": _iso(starttime),
            "minmagnitude": settings.min_magnitude,
            "orderby": "time-asc",
            "limit": settings.page_size,
            "offset": offset,
        }
        if updated_after is not None:
            params["updatedafter"] = _iso(updated_after)

        response = session.get(settings.api_url, params=params, timeout=settings.request_timeout)
        response.raise_for_status()
        page = response.json().get("features", [])
        features.extend(page)
        log.info("fetched page offset=%s records=%s", offset, len(page))

        if len(page) < settings.page_size:
            return features
        offset += settings.page_size


def read_file(path: str | Path) -> list[dict]:
    """Load features from a saved GeoJSON file (offline runs, demos, tests)."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("features", [])
