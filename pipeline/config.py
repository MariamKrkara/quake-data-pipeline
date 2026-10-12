"""Settings are read from environment variables (12-factor style), so the same
image runs unchanged under Docker Compose, Kubernetes or a cloud VM."""

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    min_magnitude: float = 2.5
    backfill_days: int = 30       # history pulled on the very first run
    lookback_days: int = 30       # event-time window for incremental runs
    overlap_minutes: int = 10     # re-read a little before the watermark to avoid gaps
    page_size: int = 5000
    interval_minutes: int = 15    # used by `run --loop`
    request_timeout: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        return cls(
            database_url=url,
            api_url=os.getenv("USGS_API_URL", cls.api_url),
            min_magnitude=_float("MIN_MAGNITUDE", cls.min_magnitude),
            backfill_days=_int("BACKFILL_DAYS", cls.backfill_days),
            lookback_days=_int("LOOKBACK_DAYS", cls.lookback_days),
            overlap_minutes=_int("OVERLAP_MINUTES", cls.overlap_minutes),
            page_size=_int("PAGE_SIZE", cls.page_size),
            interval_minutes=_int("INTERVAL_MINUTES", cls.interval_minutes),
            request_timeout=_int("REQUEST_TIMEOUT", cls.request_timeout),
        )
