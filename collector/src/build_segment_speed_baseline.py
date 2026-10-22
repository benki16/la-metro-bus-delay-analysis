import argparse
import csv
import math
from collections import defaultdict
from datetime import datetime
from route_analysis_config import load_route_profile, segment_file


MIN_BASELINE_TRIPS = 10
MIN_HOURLY_TRIPS = 5
MIN_SERVICE_DAYS = 3


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        yield from csv.DictReader(file)


def percentile(values, probability):
    values = sorted(values)

    if not values:
        return None

    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return values[lower]

    weight = position - lower

    return (
        values[lower] * (1 - weight)
        + values[upper] * weight
    )


def segment_key(row):
    return (
        row["segment_from_sequence"],
        row["segment_to_sequence"],
        row["segment_from_stop_id"],
        row["segment_to_stop_id"],
        row["segment_from_stop_name"],
        row["segment_to_stop_name"],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-key", default="route70_el_monte")
    arguments = parser.parse_args()
    route_key = arguments.route_key
    profile = load_route_profile(route_key)
    input_file = segment_file("states", route_key)
    output_file = segment_file("speed", route_key)
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    baseline_groups = defaultdict(list)
    hourly_groups = defaultdict(list)

    retained_rows = 0

    for row in read_csv(input_file):
        if row["segment_quality"] != "good":
            continue

        if row["service_date"] in profile.get("excluded_service_dates", []):
            continue

        if row["measured_speed_mph"] == "":
            continue

        observation_start = datetime.fromisoformat(
            row["segment_observation_start_la"]
        )

        hour = observation_start.hour

        if not profile["analysis_start_hour"] <= hour < profile["analysis_end_hour"]:
            continue

        speed_mph = float(
            row["measured_speed_mph"]
        )

        if speed_mph < 0:
            continue

        record = {
            "service_date": row["service_date"],
            "trip_id": row["trip_id"],
            "vehicle_id": row["vehicle_id"],
            "speed_mph": speed_mph,
            "stationary_share": float(
                row["stationary_share"]
            ),
            "stationary_near_seconds": float(
                row[
                    "stationary_near_stop_seconds"
                ]
            ),
            "stationary_away_seconds": float(
                row[
                    "stationary_away_from_stop_seconds"
                ]
            ),
        }

        key = segment_key(row)

        baseline_groups[key].append(record)
        hourly_groups[(key, hour)].append(record)

        retained_rows += 1

    output_rows = []

    for (key, hour), records in hourly_groups.items():
        baseline_records = baseline_groups[key]

        baseline_trip_keys = {
            (
                record["service_date"],
                record["trip_id"],
                record["vehicle_id"],
            )
            for record in baseline_records
        }

        hourly_trip_keys = {
            (
                record["service_date"],
                record["trip_id"],
                record["vehicle_id"],
            )
            for record in records
        }

        hourly_dates = {
            record["service_date"]
            for record in records
        }

        if (
            len(baseline_trip_keys)
            < MIN_BASELINE_TRIPS
        ):
            continue

        if len(hourly_trip_keys) < MIN_HOURLY_TRIPS:
            continue

        if len(hourly_dates) < MIN_SERVICE_DAYS:
            continue

        baseline_speeds = [
            record["speed_mph"]
            for record in baseline_records
        ]

        hourly_speeds = [
            record["speed_mph"]
            for record in records
        ]

        hourly_stationary_shares = [
            record["stationary_share"]
            for record in records
        ]

        hourly_stationary_near = [
            record["stationary_near_seconds"]
            for record in records
        ]

        hourly_stationary_away = [
            record["stationary_away_seconds"]
            for record in records
        ]

        p80_baseline_speed = percentile(
            baseline_speeds, 0.80
        )

        p50_hourly_speed = percentile(
            hourly_speeds, 0.50
        )

        speed_ratio = (
            p50_hourly_speed
            / p80_baseline_speed
            if p80_baseline_speed > 0
            else None
        )

        (
            from_sequence,
            to_sequence,
            from_stop_id,
            to_stop_id,
            from_stop_name,
            to_stop_name,
        ) = key

        output_rows.append(
            {
                "hour_start": hour,
                "hour_end": hour + 1,
                "time_window": (
                    f"{hour:02d}:00-"
                    f"{hour + 1:02d}:00"
                ),
                "segment_from_sequence": (
                    from_sequence
                ),
                "segment_to_sequence": to_sequence,
                "segment_from_stop_id": from_stop_id,
                "segment_to_stop_id": to_stop_id,
                "segment_from_stop_name": (
                    from_stop_name
                ),
                "segment_to_stop_name": to_stop_name,
                "service_day_count": len(
                    hourly_dates
                ),
                "hourly_trip_count": len(
                    hourly_trip_keys
                ),
                "baseline_trip_count": len(
                    baseline_trip_keys
                ),
                "p50_hourly_speed_mph": round(
                    p50_hourly_speed, 2
                ),
                "p80_baseline_speed_mph": round(
                    p80_baseline_speed, 2
                ),
                "speed_ratio": round(
                    speed_ratio, 4
                ),
                "median_stationary_share": round(
                    percentile(
                        hourly_stationary_shares,
                        0.50,
                    ),
                    4,
                ),
                "median_stationary_near_seconds": (
                    round(
                        percentile(
                            hourly_stationary_near,
                            0.50,
                        ),
                        2,
                    )
                ),
                "median_stationary_away_seconds": (
                    round(
                        percentile(
                            hourly_stationary_away,
                            0.50,
                        ),
                        2,
                    )
                ),
            }
        )

    output_rows.sort(
        key=lambda row: (
            row["hour_start"],
            int(row["segment_from_sequence"]),
        )
    )

    if not output_rows:
        raise ValueError(
            "No speed-baseline records were created."
        )

    with output_file.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=output_rows[0].keys(),
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print(
        f"Good trip-segment records retained: "
        f"{retained_rows}"
    )
    print(
        f"Segment-hour baseline records created: "
        f"{len(output_rows)}"
    )
    print(f"Route key: {route_key}")
    print(f"Output file: {output_file}")


if __name__ == "__main__":
    main()
    
