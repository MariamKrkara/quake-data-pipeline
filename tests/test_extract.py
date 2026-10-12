"""Extraction tests with a fake HTTP session (no network)."""

from datetime import datetime, timezone

from pipeline.config import Settings
from pipeline.extract import fetch_events


class FakeResponse:
    def __init__(self, features):
        self._features = features

    def raise_for_status(self):
        pass

    def json(self):
        return {"features": self._features}


class FakeSession:
    """Serves `total` dummy features in pages and records the requests made."""

    def __init__(self, total):
        self.total = total
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        start = params["offset"] - 1
        end = min(start + params["limit"], self.total)
        return FakeResponse([{"id": f"e{i}"} for i in range(start, end)])


def test_pagination_reads_every_page():
    settings = Settings(database_url="unused", page_size=100)
    session = FakeSession(total=250)
    features = fetch_events(settings, datetime(2026, 10, 1, tzinfo=timezone.utc), session=session)
    assert len(features) == 250
    assert [c["offset"] for c in session.calls] == [1, 101, 201]


def test_incremental_request_parameters():
    settings = Settings(database_url="unused", page_size=100, min_magnitude=4.5)
    session = FakeSession(total=0)
    fetch_events(settings, datetime(2026, 10, 1, tzinfo=timezone.utc),
                 updated_after=datetime(2026, 10, 11, 23, 50, tzinfo=timezone.utc), session=session)
    params = session.calls[0]
    assert params["updatedafter"] == "2026-10-11T23:50:00"
    assert params["starttime"] == "2026-10-01T00:00:00"
    assert params["minmagnitude"] == 4.5 and params["format"] == "geojson"
