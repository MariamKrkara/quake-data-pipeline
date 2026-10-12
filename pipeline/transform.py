"""Transform: flatten nested GeoJSON features into typed, tabular records."""

from datetime import datetime, timezone


def ms_to_datetime(ms: int | float | None) -> datetime | None:
    """USGS timestamps are milliseconds since the Unix epoch (UTC)."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def region_from_place(place: str | None) -> str | None:
    """'10 km SW of Tres Pinos, CA' -> 'CA'; 'Fiji region' -> 'Fiji region'."""
    if not place:
        return None
    return place.rsplit(", ", 1)[-1].strip()


def transform_feature(feature: dict) -> dict:
    props = feature.get("properties") or {}
    coords = list((feature.get("geometry") or {}).get("coordinates") or [])
    coords += [None] * (3 - len(coords))  # tolerate missing depth/coordinates
    longitude, latitude, depth_km = coords[:3]

    return {
        "event_id": feature.get("id"),
        "occurred_at": ms_to_datetime(props.get("time")),
        "source_updated_at": ms_to_datetime(props.get("updated")),
        "magnitude": props.get("mag"),
        "magnitude_type": props.get("magType"),
        "place": props.get("place"),
        "region": region_from_place(props.get("place")),
        "latitude": latitude,
        "longitude": longitude,
        "depth_km": depth_km,
        "event_type": props.get("type"),
        "review_status": props.get("status"),
        "tsunami_flag": bool(props.get("tsunami")),
        "significance": props.get("sig"),
        "felt_reports": props.get("felt"),
        "detail_url": props.get("url"),
    }


def dedupe_latest(records: list[dict]) -> tuple[list[dict], int]:
    """Keep only the most recently updated version of each event.

    Returns the deduplicated records and how many duplicates were dropped.
    """
    latest: dict[str, dict] = {}
    for rec in records:
        current = latest.get(rec["event_id"])
        if current is None or rec["source_updated_at"] > current["source_updated_at"]:
            latest[rec["event_id"]] = rec
    return list(latest.values()), len(records) - len(latest)
