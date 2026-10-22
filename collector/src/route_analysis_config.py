"""Shared route-aware paths and settings for the segment-map pipeline."""

import json
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIRECTORY.parents[1]
PROFILE_FILE = SCRIPT_DIRECTORY / "route_profiles.json"


def load_route_profile(route_key):
    with PROFILE_FILE.open("r", encoding="utf-8") as file:
        profiles = json.load(file)

    try:
        return profiles[route_key]
    except KeyError as error:
        available = ", ".join(sorted(profiles))
        raise ValueError(
            f"Unknown route key '{route_key}'. Available: {available}"
        ) from error


def route_data_directory(route_key):
    if route_key == "route70_el_monte":
        return PROJECT_ROOT / "data" / "processed"
    return PROJECT_ROOT / "data" / "processed" / "routes" / route_key


def enriched_file(route_key):
    if route_key == "route70_el_monte":
        return (
            PROJECT_ROOT / "data" / "processed" / "vehicle_positions"
            / "vehicle_positions_el_monte_enriched.csv"
        )
    return route_data_directory(route_key) / "vehicle_positions_enriched.csv"


def stop_events_file(route_key):
    if route_key == "route70_el_monte":
        return (
            PROJECT_ROOT / "data" / "processed" / "stop_events"
            / "route70_el_monte_stop_events.csv"
        )
    return route_data_directory(route_key) / "stop_events.csv"


def stops_file(route_key):
    if route_key == "route70_el_monte":
        return (
            PROJECT_ROOT / "data" / "processed" / "route70"
            / "stops_direction_0.csv"
        )
    return route_data_directory(route_key) / "stops.csv"


def segment_file(kind, route_key):
    folders = {
        "observations": "segment_observations",
        "states": "segment_states",
        "performance": "segment_performance",
        "summary": "segment_summary",
        "speed": "segment_summary",
    }
    suffixes = {
        "observations": "segment_observations",
        "states": "trip_segment_states",
        "performance": "segment_performance",
        "summary": "segment_hour_summary",
        "speed": "speed_baseline",
    }
    return (
        PROJECT_ROOT / "data" / "processed" / folders[kind]
        / f"{route_key}_{suffixes[kind]}.csv"
    )


def map_files(route_key):
    directory = PROJECT_ROOT / "data" / "processed" / "map"
    return (
        directory / f"{route_key}_map_data.csv",
        directory / f"{route_key}_map_data.geojson",
    )
