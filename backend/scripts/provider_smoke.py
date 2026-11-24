"""Phase 0 smoke test: TomTom truck routing + geocoding, Open-Meteo multi-location forecast.

Usage (from backend/): uv run python scripts/provider_smoke.py .env smoke-results.json
The API key is read from the .env file and never printed; error text is redacted.
Makes about 10 TomTom and 4 Open-Meteo requests. Findings: docs/phase0-findings.md.
"""

import json
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx

LB_TO_KG = 0.45359237
M_TO_MI = 1 / 1609.344


def load_key(path: str) -> str:
    with open(path) as fh:
        lines = fh.read().splitlines()
    for line in lines:
        if line.startswith("TOMTOM_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("TOMTOM_API_KEY missing")


KEY = load_key(sys.argv[1])
OUT = sys.argv[2]
client = httpx.Client(timeout=20)
results: dict = {
    "run_at": datetime.now(UTC).isoformat(),
    "routing": [],
    "geocode": [],
    "weather": {},
}


def get(url: str, params: dict) -> tuple[httpx.Response, float]:
    t0 = time.perf_counter()
    r = client.get(url, params=params)
    return r, round(time.perf_counter() - t0, 2)


def redact(text: str) -> str:
    return text.replace(KEY, "<KEY>")


def overlap(a: list[dict], b: list[dict]) -> float:
    """Share of route a's points (snapped to ~1 km) that also lie on route b."""
    sa = {(round(p["latitude"], 2), round(p["longitude"], 2)) for p in a}
    sb = {(round(p["latitude"], 2), round(p["longitude"], 2)) for p in b}
    return round(len(sa & sb) / max(len(sa), 1), 3)


def route(name, origin, dest, mode="truck", load_lb=42000, extra=None, via=None):
    depart = (datetime.now(UTC) + timedelta(hours=3)).replace(microsecond=0)
    params = {
        "key": KEY,
        "travelMode": mode,
        "maxAlternatives": 2,
        "departAt": depart.isoformat().replace("+00:00", "Z"),
        "routeType": "fastest",
        "traffic": "true",
        "computeTravelTimeFor": "all",
        "sectionType": "travelMode",
        "extendedRouteRepresentation": ["distance", "travelTime"],
    }
    if mode == "truck":
        params["vehicleWeight"] = round(load_lb * LB_TO_KG)
        params["vehicleCommercial"] = "true"
    params |= extra or {}
    locs = [origin, *(via or []), dest]
    url = (
        "https://api.tomtom.com/routing/1/calculateRoute/"
        + ":".join(f"{a},{b}" for a, b in locs)
        + "/json"
    )
    r, secs = get(url, params)
    entry = {
        "name": name,
        "mode": mode,
        "extra": {k: v for k, v in (extra or {}).items()},
        "status": r.status_code,
        "seconds": secs,
    }
    if r.status_code != 200:
        entry["error"] = redact(r.text[:500])
        results["routing"].append(entry)
        return entry
    body = r.json()
    routes = body.get("routes", [])
    entry["route_count"] = len(routes)
    entry["routes"] = []
    for i, rt in enumerate(routes):
        s = rt["summary"]
        pts = [p for leg in rt["legs"] for p in leg["points"]]
        entry["routes"].append(
            {
                "i": i,
                "distance_mi": round(s["lengthInMeters"] * M_TO_MI, 1),
                "duration_h": round(s["travelTimeInSeconds"] / 3600, 2),
                "no_traffic_h": round(s.get("noTrafficTravelTimeInSeconds", 0) / 3600, 2),
                "departure": s.get("departureTime"),
                "arrival": s.get("arrivalTime"),
                "points": len(pts),
                "summary_keys": sorted(s),
                "sections": [
                    sec.get("sectionType") + ":" + str(sec.get("travelMode"))
                    for sec in rt.get("sections", [])
                ][:5],
                "route_keys": sorted(rt),
                "progress_len": len(rt.get("progress", [])),
                "progress_sample": rt.get("progress", [])[:2] + rt.get("progress", [])[-1:],
                "legs": len(rt["legs"]),
                "avg_mph": round(
                    s["lengthInMeters"] * M_TO_MI / (s["travelTimeInSeconds"] / 3600), 1
                ),
            }
        )
        entry["routes"][-1]["_pts"] = pts
    for i in range(len(routes)):
        for j in range(len(routes)):
            if i < j:
                entry.setdefault("overlap", {})[f"{i}-{j}"] = overlap(
                    entry["routes"][i]["_pts"], entry["routes"][j]["_pts"]
                )
    for rt in entry["routes"]:
        del rt["_pts"]
    entry["top_level_keys"] = sorted(body)
    results["routing"].append(entry)
    return entry


DALLAS, DENVER = (32.7767, -96.7970), (39.7392, -104.9903)
CHICAGO, ATLANTA = (41.8781, -87.6298), (33.7490, -84.3880)
LA, PHOENIX = (34.0522, -118.2437), (33.4484, -112.0740)

route("Dallas->Denver truck 42k lb", DALLAS, DENVER)
route("Chicago->Atlanta truck 42k lb", CHICAGO, ATLANTA)
route("LA->Phoenix truck 42k lb", LA, PHOENIX)
route("Dallas->Denver car 65mph cap", DALLAS, DENVER, mode="car", extra={"vehicleMaxSpeed": 105})
route(
    "Dallas->Denver truck minDeviation (GET)",
    DALLAS,
    DENVER,
    extra={"minDeviationDistance": 0, "minDeviationTime": 0},
)
route("Dallas->Denver truck via perpendicular offset", DALLAS, DENVER, via=[(37.6, -97.3)])

for q in ["Dallas, TX", "Denver", "1600 Pennsylvania Ave, Washington DC", "Toronto"]:
    r, secs = get(
        f"https://api.tomtom.com/search/2/geocode/{q}.json",
        {"key": KEY, "countrySet": "US", "limit": 5},
    )
    e = {"q": q, "status": r.status_code, "seconds": secs}
    if r.status_code == 200:
        e["results"] = [
            {
                "label": x["address"].get("freeformAddress"),
                "type": x.get("type"),
                "country": x["address"].get("countryCode"),
                "lat": x["position"]["lat"],
                "lon": x["position"]["lon"],
            }
            for x in r.json().get("results", [])
        ]
    else:
        e["error"] = redact(r.text[:300])
    results["geocode"].append(e)

# Open-Meteo: 3 locations on the 0.1 deg lattice, 5 variables, UTC, a bounded hour window.
start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
end = start + timedelta(hours=48)
lats, lons = [32.8, 35.2, 39.7], [-96.8, -101.8, -105.0]
r, secs = get(
    "https://api.open-meteo.com/v1/forecast",
    {
        "latitude": ",".join(map(str, lats)),
        "longitude": ",".join(map(str, lons)),
        "hourly": "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    },
)
w: dict = {"status": r.status_code, "seconds": secs}
if r.status_code == 200:
    body = r.json()
    w["is_list"] = isinstance(body, list)
    loc = body[0] if isinstance(body, list) else body
    w["locations"] = len(body) if isinstance(body, list) else 1
    w["keys"] = sorted(loc)
    w["snapped_coords"] = [
        (b["latitude"], b["longitude"]) for b in (body if isinstance(body, list) else [body])
    ]
    w["timezone"] = loc.get("timezone")
    w["hourly_units"] = loc.get("hourly_units")
    w["n_hours"] = len(loc["hourly"]["time"])
    w["first_times"] = loc["hourly"]["time"][:3]
    w["sample"] = {k: v[:3] for k, v in loc["hourly"].items()}
    w["null_counts"] = {k: sum(x is None for x in v) for k, v in loc["hourly"].items()}
else:
    w["error"] = r.text[:300]
results["weather"]["multi_location"] = w

# Forecast horizon: day 7, day 15 and day 17 from now.
for label, days in [("day7_8", 7), ("day15_16", 15), ("day17", 17)]:
    s = start + timedelta(days=days)
    r, secs = get(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": 39.7,
            "longitude": -105.0,
            "hourly": "wind_speed_10m,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "start_hour": s.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": (s + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"),
        },
    )
    entry = {"status": r.status_code}
    if r.status_code == 200:
        h = r.json()["hourly"]
        entry["times"] = h["time"]
        entry["wind"] = h["wind_speed_10m"]
    else:
        entry["error"] = r.text[:200]
    results["weather"][f"horizon_{label}"] = entry

with open(OUT, "w") as fh:
    json.dump(results, fh, indent=2)
print(f"Wrote {OUT}")
