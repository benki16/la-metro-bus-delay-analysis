import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
LOG_DIRECTORY = PROJECT_ROOT / "logs"
PROFILE_FILE = SCRIPT_DIRECTORY / "route_profiles.json"

LOS_ANGELES_TIMEZONE = ZoneInfo("America/Los_Angeles")
COLLECTION_END_HOUR = 20

# Keep the existing processing order unchanged.
PROCESSING_SCRIPTS = [
    "normalize_vehicle_positions_multi_route.py",
    "enrich_vehicle_positions_multi_route.py",
    "build_stop_events_multi_route.py",
]

# Rebuild the small dashboard outputs after the route's new stop events exist.
# This keeps the three map layers current after each daily collection.
MAP_ANALYSIS_SCRIPTS = [
    "build_observation_segments.py",
    "build_trip_segment_states.py",
    "build_segment_performance.py",
    "build_segment_hour_summary.py",
    "build_segment_speed_baseline.py",
    "build_map_dataset.py",
]


def load_route_keys():
    with PROFILE_FILE.open("r", encoding="utf-8") as file:
        profiles = json.load(file)

    if not profiles:
        raise ValueError("route_profiles.json does not contain any routes.")

    return list(profiles)


def write_log(log_file, message):
    timestamp = datetime.now(LOS_ANGELES_TIMEZONE).isoformat()
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    log_file.write(log_line + "\n")
    log_file.flush()


def run_script(log_file, script_name, arguments=None):
    command = [sys.executable, str(SCRIPT_DIRECTORY / script_name)]

    if arguments:
        command.extend(arguments)

    write_log(log_file, f"Starting: {' '.join(command)}")

    result = subprocess.run(
        command,
        cwd=SCRIPT_DIRECTORY,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{script_name} failed with exit code {result.returncode}"
        )

    write_log(log_file, f"Completed: {script_name}")


def calculate_collection_minutes():
    now_la = datetime.now(LOS_ANGELES_TIMEZONE)
    end_time = now_la.replace(
        hour=COLLECTION_END_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    remaining_seconds = (end_time - now_la).total_seconds()
    return max(remaining_seconds, 0) / 60


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-minutes",
        type=float,
        help="Run a short collection test instead of collecting until 8 PM.",
    )
    args = parser.parse_args()

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    current_date_la = datetime.now(LOS_ANGELES_TIMEZONE).strftime("%Y%m%d")
    log_path = LOG_DIRECTORY / f"daily_pipeline_{current_date_la}.log"

    with log_path.open("a", encoding="utf-8") as log_file:
        write_log(log_file, "Daily pipeline started")

        try:
            route_keys = load_route_keys()
            write_log(log_file, "Routes: " + ", ".join(route_keys))

            if args.test_minutes is not None:
                collection_minutes = args.test_minutes
                write_log(log_file, "Running in test mode")
            else:
                collection_minutes = calculate_collection_minutes()

            if collection_minutes <= 0:
                write_log(
                    log_file,
                    "Collection window has already ended. Pipeline stopped.",
                )
                return

            run_script(
                log_file,
                "vehicle_positions_multi_route.py",
                ["--minutes", str(collection_minutes)],
            )

            # Preserve the old order: normalize every route, then enrich every
            # route, then build every route's stop events.
            for script_name in PROCESSING_SCRIPTS:
                for route_key in route_keys:
                    run_script(
                        log_file,
                        script_name,
                        ["--route-key", route_key],
                    )

            for script_name in MAP_ANALYSIS_SCRIPTS:
                for route_key in route_keys:
                    run_script(
                        log_file,
                        script_name,
                        ["--route-key", route_key],
                    )

            write_log(log_file, "Daily pipeline completed successfully")

        except Exception as error:
            write_log(log_file, f"Pipeline failed: {error}")
            raise


if __name__ == "__main__":
    main()
