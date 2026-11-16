"""Prefect-managed refresh: calculate first, then publish both files atomically."""
from pathlib import Path
import json
import tempfile

from prefect import flow, get_run_logger
from prefect.artifacts import create_link_artifact
from prefect.blocks.system import Secret
import requests

from iss_planner import SITE_URL, generate

REPO = "dorrino-gif/iss-viewing-planner"


def publish_dataset(token, files):
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + token,
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"})
    base = "https://api.github.com/repos/" + REPO
    def api(path, method="GET", payload=None):
        response = session.request(method, base + path, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    # All generation and validation have completed before the first repository write.
    head = api("/git/ref/heads/main")["object"]["sha"]
    parent = api("/git/commits/" + head)
    tree = api("/git/trees", "POST", {"base_tree": parent["tree"]["sha"], "tree": [
        {"path": path, "mode": "100644", "type": "blob", "content": content}
        for path, content in files.items()]})
    commit = api("/git/commits", "POST", {"message": "Refresh ISS viewing estimates and seven-day weather",
        "tree": tree["sha"], "parents": [head]})
    # Reject a concurrent change rather than overwriting it.
    api("/git/refs/heads/main", "PATCH", {"sha": commit["sha"], "force": False})
    return commit["sha"]


@flow(name="iss-viewing-refresh", log_prints=False, timeout_seconds=1500)
def refresh_viewing(latitude: float = 35.7796, longitude: float = -78.6382,
                    location: str = "Raleigh, NC", start_time: str = "now",
                    forecast_days: int = 30, weather_days: int = 7,
                    reminder_minutes: int = 15):
    """Compute thirty orbital days and seven weather days, then update GitHub Pages.

    Requires the `iss-viewing-github` Secret block with Contents read/write access
    limited to dorrino-gif/iss-viewing-planner. Publication is gated by the parent
    execution plan's human approval. This deployment has no recurring schedule.
    """
    logger = get_run_logger()
    token = Secret.load("iss-viewing-github").get()
    if not token:
        raise ValueError("The iss-viewing-github Secret block is empty")
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "data"
        data = generate(latitude, longitude, location, start_time, forecast_days,
                        weather_days, reminder_minutes, str(output), str(Path(temp) / "cache"))
        commit = publish_dataset(token, {
            "docs/data/predictions.json": (output / "predictions.json").read_text(),
            "docs/data/all-passes.ics": (output / "all-passes.ics").read_bytes().decode("utf-8"),
        })
    logger.info("Published %s viewing windows in commit %s; GitHub Pages may take a few minutes to update.", len(data["passes"]), commit)
    create_link_artifact(key="iss-viewing-map", link=SITE_URL,
        description="ISS viewing map. A successful repository update can precede GitHub Pages publication by a few minutes.")
    return {"map_url": SITE_URL, "calendar_url": SITE_URL + "data/all-passes.ics",
            "commit_sha": commit, "pass_count": len(data["passes"]),
            "generated_at": data["generated_at"], "warnings": data["warnings"]}
