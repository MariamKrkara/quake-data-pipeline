"""Unit tests: no database or network needed."""

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.quality import check_record, split_valid
from pipeline.transform import dedupe_latest, region_from_place, transform_feature

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def batch(name):
    return json.loads((FIXTURES / name).read_text())["features"]


def test_transform_flattens_geojson():
    rec = transform_feature(batch("usgs_batch_1.geojson")[0])
    assert rec["event_id"] == "us7000r1a1"
    assert rec["occurred_at"] == datetime(2026, 10, 1, 3, 12, 44, tzinfo=timezone.utc)
    assert (rec["longitude"], rec["latitude"], rec["depth_km"]) == (166.21, -11.62, 35.0)
    assert rec["region"] == "Solomon Islands"
    assert rec["magnitude_type"] == "mww"


def test_transform_tolerates_missing_geometry():
    rec = transform_feature({"id": "x1", "properties": {}})
    assert rec["latitude"] is None and rec["longitude"] is None and rec["depth_km"] is None


def test_region_from_place():
    assert region_from_place("10 km SW of Tres Pinos, CA") == "CA"
    assert region_from_place("Fiji region") == "Fiji region"
    assert region_from_place(None) is None


def test_quality_rules():
    good = transform_feature(batch("usgs_batch_1.geojson")[0])
    assert check_record(good, NOW) == []
    assert "latitude out of range" in check_record({**good, "latitude": 123.4}, NOW)
    assert "missing magnitude" in check_record({**good, "magnitude": None}, NOW)
    assert "event time in the future" in check_record(
        {**good, "occurred_at": datetime(2027, 1, 1, tzinfo=timezone.utc)}, NOW)


def test_split_and_dedupe_batch_1():
    feats = batch("usgs_batch_1.geojson")
    valid, rejected = split_valid([(f, transform_feature(f)) for f in feats], NOW)
    assert len(rejected) == 2
    deduped, dups = dedupe_latest(valid)
    assert dups == 1 and len(deduped) == 7
    alaska = next(r for r in deduped if r["event_id"] == "ak0260abc1")
    assert alaska["magnitude"] == 3.1  # newest version kept
