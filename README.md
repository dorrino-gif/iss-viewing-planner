# Look Up — ISS Viewing Planner

An ISS viewing planner for **Raleigh, North Carolina**: thirty days of orbital estimates, seven days of cloud forecasts, a regional visibility map, a global flight-path timeline, and downloadable calendar reminders.

**Website:** https://dorrino-gif.github.io/iss-viewing-planner/

**Prefect workflow:** https://app.prefect.cloud/account/1b5a6c7b-1b06-4c0c-ac92-a987bfd47057/workspace/15de85c6-c0d7-4c09-a0f8-0cbd514e9320/flows/flow/d91ec1e6-b180-4b65-8574-09e9a1234bfd

Published execution-plan version: `06afb3ec-5fcb-7f8e-8000-407f3dc9d10f`.
For a default manual run, supply `{"request": {}}`; review and answer the publication form when it appears. A GitHub Secret block must be configured before allowing publication. No end-to-end Cloud test run has been performed during initial setup.

## What the colors mean

The ISS must be sunlit, the observer's Sun must be at least 6° below the horizon, and the ISS must be at least 10° above it. Best viewing requires visible elevation of at least 40° and cloud cover no higher than 30%, when weather is available. Partial viewing requires visible elevation of at least 10° and cloud cover no higher than 70%. Higher cloud cover is poor. Without a cloud forecast, classifications describe **geometry only**.

Regional cells represent samples at their centers across roughly 450 × 500 km around Raleigh, at 0.5° latitude × 0.625° longitude resolution. They are approximate viewing zones, not exact boundaries. Terrain, buildings, local cloud patches, and brightness variation are not modeled. Flight-path lines are ground tracks, not visibility boundaries. A visible window can begin or end during a pass when the ISS enters shadow or the observer's sky becomes too bright.

## Forecast limits

- Orbital estimates cover exactly 30 days. Days 8–14 are tentative; days 15–30 have low confidence. Maneuvers can change predicted times. Refresh and recheck before observing.
- Weather is requested from Open-Meteo for seven days, and never attached at or beyond seven days after the forecast start. Missing forecasts are explicitly unavailable, not clear skies. Provider coverage may end earlier than the rolling seven-day boundary.
- Orbit data is cached for two hours and rejected when its epoch is more than three days from the calculation time.
- Pass visibility is sampled at five seconds; regional zones at twenty seconds; global orbit at two minutes. All are estimates.
- Calendar times are encoded in UTC, so calendar apps display the correct local time across daylight-saving changes. Reminders default to fifteen minutes before the visible window. **Imported events are snapshots and do not update automatically.** Reimporting a refresh may create duplicates, depending on the calendar app.
- The page warns when published data is more than 36 hours old. There is no automatic refresh schedule until one is explicitly configured.

## Prefect workflow

The agentic execution plan prepares and validates run parameters with Prefect's `claude-opus-5-5`, waits for human publication approval, then invokes the deterministic `iss-viewing-refresh` deployment. The deployment fetches public data, computes and validates predictions, and commits the JSON and calendar together to `main`. GitHub Pages publishes the `docs/` directory. The deployment returns publication metadata and creates a map link artifact.

No MCP connection is needed by this deployment. It reads a Prefect **Secret** block named `iss-viewing-github`, containing a fine-grained token restricted to this repository with Contents read/write. Never put credentials in the repository or execution-plan inputs. Protect direct deployment access as appropriate: running the deployment directly bypasses the parent plan's human checkpoint.

The initial setup uses Prefect-managed compute (`iss-viewing-managed`, small compute profile). The deployment has no recurring schedule. Execution-plan schema 0.2 cannot enforce Prefect expectations; mechanical checks live in `iss_planner.py` and its tests.

### Local calculation

Use Python 3.10+ for Prefect. The standalone astronomy calculator also works on Python 3.9.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python iss_planner.py
.venv/bin/python -m pytest -q
node tests/calendar.test.cjs
python3 -m http.server 8080 --directory docs
```

The local calculation reads public data and writes `docs/data/predictions.json` and `docs/data/all-passes.ics`; it does not publish. Generated JSON is ignored locally to prevent accidental stale commits; the Prefect publisher writes it intentionally through GitHub's API.

### Sources and attribution

- [CelesTrak GP/OMM orbital elements](https://celestrak.org/NORAD/documentation/gp-data-formats.php), ISS NORAD 25544.
- [Skyfield](https://rhodesmill.org/skyfield/earth-satellites.html) and SGP4 for satellite propagation; JPL DE421 for solar geometry.
- [Open-Meteo](https://open-meteo.com/en/docs) for hourly cloud cover and precipitation probability. Review its terms before commercial use or higher-volume operation.
- [Leaflet](https://leafletjs.com/) and [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) for the map. Map tiles and fonts load from third-party services.
