from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from iss_planner import quality, weather_at, calendar_bytes, fold_line, validate_dataset


def test_weather_horizon_is_strict_and_absence_is_not_clear_sky():
    start = datetime(2026, 11, 16, tzinfo=timezone.utc)
    point = (35.7796, -78.6382)
    cutoff = start + timedelta(days=7)
    weather = {point: [(cutoff.timestamp() - 3600, 75., 10), (cutoff.timestamp(), 0., 0)]}
    assert weather_at(weather, point, cutoff - timedelta(minutes=10), start) is not None
    assert weather_at(weather, point, cutoff, start) is None
    assert weather_at({}, point, start, start) is None
    assert quality(60, 75) == "poor"
    assert quality(60, 30) == "best"
    assert quality(39, 0) == "partial"
    assert quality(9, 0) == "poor"


def test_calendar_uses_utc_stable_ids_and_utf8_folding():
    data = {"generated_at": "2026-11-16T17:00:00Z", "location": {"name": "Raleigh, NC"},
            "reminder_minutes": 15, "passes": [{"id": "stable-id", "start": "2026-11-17T00:03:00Z",
            "end": "2026-11-17T00:07:00Z", "weather": None, "max_elevation": 55,
            "start_azimuth": 10, "end_azimuth": 200}]}
    raw = calendar_bytes(data)
    assert b"DTSTART:20261117T000300Z\r\n" in raw
    assert b"UID:stable-id@iss-viewing-planner" in raw
    assert b"TRIGGER:-PT15M" in raw
    assert b"LOCATION:Raleigh\\, NC" in raw
    assert b"update automatically" in raw.replace(b"\r\n ", b"")
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
    assert all(len(line.encode()) <= 75 for line in fold_line("é" * 100).split("\r\n"))


def test_generated_forecast_has_valid_orbit_and_weather_boundaries():
    path = Path("docs/data/predictions.json")
    if not path.exists():
        import pytest
        pytest.skip("Generate a live forecast to run this integration check")
    data = json.loads(path.read_text())
    validate_dataset(data)
    assert len(data["orbit"]) == 21601
    assert data["passes"], "Live validation needs at least one visible pass"
    assert all(-90 <= row[1] <= 90 and -180 <= row[2] <= 180 for row in data["orbit"])
    cutoff = datetime.fromisoformat(data["weather_cutoff"].replace("Z", "+00:00"))
    for item in data["passes"]:
        if datetime.fromisoformat(item["peak"].replace("Z", "+00:00")) >= cutoff:
            assert item["weather"] is None
            assert all(f["properties"]["weather"] is None for f in item["zones"]["features"])
