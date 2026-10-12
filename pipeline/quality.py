"""Data-quality rules. Each failing record is quarantined with its reasons
instead of being silently dropped or breaking the load."""

from datetime import datetime, timedelta, timezone

REQUIRED = ("event_id", "occurred_at", "source_updated_at", "latitude", "longitude")


def check_record(record: dict, now: datetime | None = None) -> list[str]:
    """Return the list of rule violations (empty list = record is valid)."""
    now = now or datetime.now(timezone.utc)
    reasons = [f"missing {field}" for field in REQUIRED if record.get(field) is None]

    lat, lon, depth, mag = (record.get(k) for k in ("latitude", "longitude", "depth_km", "magnitude"))
    if lat is not None and not -90 <= lat <= 90:
        reasons.append("latitude out of range")
    if lon is not None and not -180 <= lon <= 180:
        reasons.append("longitude out of range")
    if depth is not None and not -10 <= depth <= 1000:
        reasons.append("depth out of range")
    if mag is None:
        reasons.append("missing magnitude")
    elif not -2 <= mag <= 10:
        reasons.append("magnitude out of range")

    occurred = record.get("occurred_at")
    if occurred is not None and occurred > now + timedelta(hours=1):
        reasons.append("event time in the future")
    return reasons


def split_valid(pairs: list[tuple[dict, dict]], now: datetime | None = None):
    """Split (raw_feature, record) pairs into valid records and rejections."""
    valid, rejected = [], []
    for feature, record in pairs:
        reasons = check_record(record, now)
        if reasons:
            rejected.append((feature, record, reasons))
        else:
            valid.append(record)
    return valid, rejected
