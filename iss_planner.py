"""Deterministic ISS predictions, regional visibility zones, and calendar export."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math
import time

import numpy as np
import requests
from skyfield.api import EarthSatellite, Loader, wgs84

UTC = timezone.utc
ORBIT_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=JSON"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
SITE_URL = "https://dorrino-gif.github.io/iss-viewing-planner/"


def iso(dt):
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_date(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Start time must include a time zone")
    return dt.astimezone(UTC)


def get_json(url, params=None):
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=(10, 60),
                                    headers={"User-Agent": "iss-viewing-planner/1.0 (personal astronomy project)"})
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def orbit_elements(cache, now):
    path = cache / "iss-omm.json"
    # CelesTrak requests at most once every two hours, including local reruns.
    if path.exists() and now.timestamp() - path.stat().st_mtime < 7200:
        data = json.loads(path.read_text())
    else:
        data = get_json(ORBIT_URL)
        if not data or data[0].get("NORAD_CAT_ID") != 25544:
            raise ValueError("Source did not return the ISS")
        path.write_text(json.dumps(data))
    epoch = parse_date(data[0]["EPOCH"] + ("Z" if "+" not in data[0]["EPOCH"] and not data[0]["EPOCH"].endswith("Z") else ""))
    if abs((now - epoch).total_seconds()) > 3 * 86400:
        raise ValueError("ISS orbital elements are over three days old; refusing to publish stale predictions")
    return data[0], epoch


def quality(elevation, cloud=None):
    """No cloud value means a geometry-only classification, never clear weather."""
    if elevation < 10:
        return "poor"
    if cloud is not None and cloud > 70:
        return "poor"
    if elevation >= 40 and (cloud is None or cloud <= 30):
        return "best"
    return "partial"


def regional_grid(latitude, longitude):
    return [(round(latitude + dy * .5, 4), round(longitude + dx * .625, 4))
            for dy in range(-4, 5) for dx in range(-4, 5)]


def fetch_weather(grid, start):
    warnings = []
    now = datetime.now(UTC)
    if start > now + timedelta(hours=1) or start < now - timedelta(hours=1):
        return {}, ["Weather is available only for a forecast starting now; historical/future-start runs use geometry only."]
    try:
        result = get_json(WEATHER_URL, {
            "latitude": ",".join(str(p[0]) for p in grid),
            "longitude": ",".join(str(p[1]) for p in grid),
            "hourly": "cloud_cover,precipitation_probability",
            "forecast_days": 7, "timezone": "UTC", "timeformat": "unixtime",
        })
        if isinstance(result, dict):
            result = [result]
        if len(result) != len(grid):
            raise ValueError("Weather response has missing locations")
        weather = {}
        for point, item in zip(grid, result):
            hourly = item["hourly"]
            rows = []
            for stamp, cloud, rain in zip(hourly["time"], hourly["cloud_cover"], hourly["precipitation_probability"]):
                if cloud is not None:
                    rows.append((stamp, float(cloud), rain))
            weather[point] = rows
        return weather, warnings
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {}, ["Cloud forecasts could not be retrieved. All viewing ratings are geometry only."]


def weather_at(weather, point, dt, start):
    # Strict rolling seven-day boundary, even if the provider supplies more.
    if not start <= dt < start + timedelta(days=7):
        return None
    rows = weather.get(point, [])
    if not rows:
        return None
    stamp = dt.timestamp()
    if stamp < rows[0][0] or stamp > rows[-1][0]:
        return None
    index = min(range(len(rows)), key=lambda i: abs(rows[i][0] - stamp))
    row = rows[index]
    if abs(row[0] - stamp) > 3600:
        return None
    return {"cloud_cover": row[1], "precipitation_probability": row[2],
            "forecast_time": iso(datetime.fromtimestamp(row[0], UTC))}


def sample_times(ts, start, end, seconds):
    count = max(2, math.ceil((end - start).total_seconds() / seconds) + 1)
    stamps = np.linspace(start.timestamp(), end.timestamp(), count)
    dates = [datetime.fromtimestamp(float(s), UTC) for s in stamps]
    return ts.from_datetimes(dates), dates


def visible_segments(mask):
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    return np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)


def assess(satellite, eph, observer, times):
    topocentric = (satellite - observer).at(times)
    alt, az, _ = topocentric.altaz()
    sun_alt = (eph["earth"] + observer).at(times).observe(eph["sun"]).apparent().altaz()[0].degrees
    sunlit = satellite.at(times).is_sunlit(eph)
    mask = (alt.degrees >= 10) & (sun_alt <= -6) & sunlit
    return alt.degrees, az.degrees, mask


def ground_track(satellite, ts, center):
    times, dates = sample_times(ts, center - timedelta(minutes=45), center + timedelta(minutes=45), 30)
    subpoint = wgs84.subpoint(satellite.at(times))
    return [[iso(d), round(float(lat), 4), round(float(lon), 4)]
            for d, lat, lon in zip(dates, subpoint.latitude.degrees, subpoint.longitude.degrees)]


def zones_for_pass(satellite, eph, ts, start, end, grid, weather, forecast_start):
    times, dates = sample_times(ts, start - timedelta(minutes=8), end + timedelta(minutes=8), 20)
    features = []
    for lat, lon in grid:
        alt, _, mask = assess(satellite, eph, wgs84.latlon(lat, lon), times)
        indices = np.flatnonzero(mask)
        best = int(indices[np.argmax(alt[indices])]) if len(indices) else int(np.argmax(alt))
        elevation = float(alt[best]) if len(indices) else 0.
        conditions = weather_at(weather, (lat, lon), dates[best], forecast_start)
        cloud = conditions["cloud_cover"] if conditions else None
        rating = quality(elevation, cloud)
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[
            [lon - .3125, lat - .25], [lon + .3125, lat - .25],
            [lon + .3125, lat + .25], [lon - .3125, lat + .25], [lon - .3125, lat - .25]]]},
            "properties": {"quality": rating, "max_elevation": round(elevation, 1),
                           "weather": conditions, "basis": "weather_and_geometry" if conditions else "geometry_only"}})
    return {"type": "FeatureCollection", "features": features}


def generate(latitude=35.7796, longitude=-78.6382, location="Raleigh, NC",
             start_time="now", forecast_days=30, weather_days=7, reminder_minutes=15,
             output_dir="docs/data", cache_dir=".cache"):
    if not (-85 <= latitude <= 85 and -177 <= longitude <= 177):
        raise ValueError("Location outside supported regional-map bounds")
    if forecast_days != 30 or weather_days != 7:
        raise ValueError("This workflow requires 30 orbital days and seven weather days")
    if not 0 <= reminder_minutes <= 1440:
        raise ValueError("Invalid reminder lead time")
    now = datetime.now(UTC)
    start = now if start_time == "now" else parse_date(start_time)
    end = start + timedelta(days=forecast_days)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    elements, epoch = orbit_elements(cache, now)
    loader = Loader(str(cache))
    ts = loader.timescale()
    eph = loader("de421.bsp")
    satellite = EarthSatellite.from_omm(ts, elements)
    observer = wgs84.latlon(latitude, longitude)
    grid = regional_grid(latitude, longitude)
    weather, warnings = fetch_weather(grid, start)
    event_times, events = satellite.find_events(observer, ts.from_datetime(start), ts.from_datetime(end), altitude_degrees=10)
    windows = []
    rise = start
    for event_time, event in zip(event_times, events):
        dt = event_time.utc_datetime()
        if event == 0:
            rise = dt
        elif event == 2:
            windows.append((rise, dt))
            rise = None
    if rise is not None:
        alt = (satellite - observer).at(ts.from_datetime(end)).altaz()[0].degrees
        if alt >= 10:
            windows.append((rise, end))
    passes = []
    for rise, setting in windows:
        if rise is None or setting <= rise:
            continue
        times, dates = sample_times(ts, rise, setting, 5)
        alt, az, mask = assess(satellite, eph, observer, times)
        for indices in visible_segments(mask):
            if len(indices) < 3:
                continue
            first, last = int(indices[0]), int(indices[-1])
            peak = int(indices[np.argmax(alt[indices])])
            visible_start, visible_end, peak_dt = dates[first], dates[last], dates[peak]
            conditions = weather_at(weather, (round(latitude, 4), round(longitude, 4)), peak_dt, start)
            cloud = conditions["cloud_cover"] if conditions else None
            elevation = float(alt[peak])
            pass_id = hashlib.sha256((iso(visible_start) + str(latitude) + str(longitude)).encode()).hexdigest()[:16]
            days_ahead = (peak_dt - now).total_seconds() / 86400
            passes.append({
                "id": pass_id, "start": iso(visible_start), "end": iso(visible_end), "peak": iso(peak_dt),
                "duration_seconds": round((visible_end - visible_start).total_seconds()),
                "max_elevation": round(elevation, 1), "start_azimuth": round(float(az[first]), 1),
                "end_azimuth": round(float(az[last]), 1), "quality": quality(elevation, cloud),
                "weather": conditions, "basis": "weather_and_geometry" if conditions else "geometry_only",
                "confidence": "near_term" if days_ahead <= 7 else "tentative" if days_ahead <= 14 else "low",
                "track": ground_track(satellite, ts, peak_dt),
                "zones": zones_for_pass(satellite, eph, ts, rise, setting, grid, weather, start),
            })
    orbit_times, orbit_dates = sample_times(ts, start, end, 120)
    subpoint = wgs84.subpoint(satellite.at(orbit_times))
    orbit = [[iso(d), round(float(a), 3), round(float(b), 3)]
             for d, a, b in zip(orbit_dates, subpoint.latitude.degrees, subpoint.longitude.degrees)]
    dataset = {
        "schema_version": 1, "generated_at": iso(now), "start": iso(start), "end": iso(end),
        "orbital_epoch": iso(epoch), "forecast_days": 30, "weather_days": 7,
        "weather_cutoff": iso(start + timedelta(days=7)), "reminder_minutes": reminder_minutes,
        "location": {"name": location, "latitude": latitude, "longitude": longitude, "timezone": "America/New_York"},
        "sources": {"orbit": ORBIT_URL, "weather": WEATHER_URL},
        "method": {"minimum_elevation": 10, "best_elevation": 40, "sun_altitude_max": -6,
                   "best_cloud_max": 30, "partial_cloud_max": 70, "grid_resolution_degrees": [.5, .625],
                   "zone_note": "Regional sampled estimates; each cell represents its center. Terrain, obstructions, and local cloud differences are not modeled."},
        "warnings": warnings + ["Estimates beyond seven days are tentative, especially beyond fourteen days. Recheck before viewing; ISS maneuvers can change pass times.",
                                "Calendar downloads are snapshots and will not update automatically."],
        "passes": passes, "orbit": orbit,
    }
    validate_dataset(dataset)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # One atomic JSON replacement; never expose a half-written dataset.
    temp = output / "predictions.tmp"
    temp.write_text(json.dumps(dataset, separators=(",", ":"), allow_nan=False))
    temp.replace(output / "predictions.json")
    (output / "all-passes.ics").write_bytes(calendar_bytes(dataset))
    return dataset


def validate_dataset(data):
    start, end = parse_date(data["start"]), parse_date(data["end"])
    if end - start != timedelta(days=30) or data["weather_days"] != 7:
        raise ValueError("Invalid forecast horizon")
    ids = set()
    previous = start
    for item in data["passes"]:
        a, peak, b = map(parse_date, [item["start"], item["peak"], item["end"]])
        if not start <= a <= peak <= b <= end or a < previous or item["id"] in ids:
            raise ValueError("Invalid or duplicate pass interval")
        ids.add(item["id"])
        previous = a
        if peak >= start + timedelta(days=7) and item["weather"] is not None:
            raise ValueError("Weather appears beyond seven days")
        if not 10 <= item["max_elevation"] <= 90.1:
            raise ValueError("Invalid viewing elevation")
        if len(item["zones"]["features"]) != 81:
            raise ValueError("Regional zones are incomplete")


def ics_escape(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_line(value):
    lines, current = [], ""
    for char in value:
        if len((current + char).encode("utf-8")) > 75:
            lines.append(current)
            current = " "
        current += char
    lines.append(current)
    return "\r\n".join(lines)


def calendar_bytes(data, selected_id=None):
    fmt = lambda value: parse_date(value).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ISS Viewing Planner//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for item in data["passes"]:
        if selected_id and item["id"] != selected_id:
            continue
        conditions = item["weather"]
        cloud = str(round(conditions["cloud_cover"])) + "%" if conditions else "unavailable; geometry only"
        description = (f"Peak elevation {item['max_elevation']} degrees. Clouds: {cloud}. "
                       f"Look from azimuth {item['start_azimuth']} to {item['end_azimuth']} degrees. "
                       "Times are estimates. Recheck before viewing. This imported event will not update automatically.")
        lines += ["BEGIN:VEVENT", "UID:" + item["id"] + "@iss-viewing-planner", "DTSTAMP:" + fmt(data["generated_at"]),
                  "DTSTART:" + fmt(item["start"]), "DTEND:" + fmt(item["end"]),
                  "SUMMARY:" + ics_escape("ISS viewing — " + data["location"]["name"]),
                  "LOCATION:" + ics_escape(data["location"]["name"]), "DESCRIPTION:" + ics_escape(description),
                  "URL:" + SITE_URL + "#pass=" + item["id"], "BEGIN:VALARM", "ACTION:DISPLAY",
                  "DESCRIPTION:ISS viewing begins soon", "TRIGGER:-PT" + str(data["reminder_minutes"]) + "M",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold_line(line) for line in lines) + "\r\n").encode("utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="docs/data")
    args = parser.parse_args()
    result = generate(output_dir=args.output_dir)
    print(json.dumps({"generated_at": result["generated_at"], "passes": len(result["passes"]), "warnings": result["warnings"]}))
