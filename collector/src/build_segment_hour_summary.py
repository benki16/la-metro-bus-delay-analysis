import argparse
import csv
import statistics
from collections import defaultdict
from datetime import datetime
from route_analysis_config import load_route_profile, segment_file



def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        yield from csv.DictReader(file)


def median(values):
    return round(statistics.median(values), 2)


def mean(values):
    return round(statistics.mean(values), 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-key", default="route70_el_monte")
    arguments = parser.parse_args()
    route_key = arguments.route_key
    profile = load_route_profile(route_key)
    input_file = segment_file("performance", route_key)
    output_file = segment_file("summary", route_key)
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    groups = defaultdict(list)

    for row in read_csv(input_file):
        if row["segment_quality"] != "good":
            continue

        if (
            row["schedule_comparison_quality"]
            != "valid"
        ):
            continue

        departure_time = datetime.fromisoformat(
            row["actual_departure_from_stop_la"]
        )

        hour = departure_time.hour

        if not profile["analysis_start_hour"] <= hour < profile["analysis_end_hour"]:
            continue

        day_type = (
            "holiday"
            if row["service_date"] in profile.get("excluded_service_dates", [])
            else "regular"
        )

        key = (
            day_type,
            hour,
            row["segment_from_sequence"],
            row["segment_to_sequence"],
            row["segment_from_stop_id"],
            row["segment_to_stop_id"],
            row["segment_from_stop_name"],
            row["segment_to_stop_name"],
        )

        groups[key].append(row)

    output_rows = []

    for key, rows in groups.items():
        (
            day_type,
            hour,
            from_sequence,
            to_sequence,
            from_stop_id,
            to_stop_id,
            from_stop_name,
            to_stop_name,
        ) = key

        actual_times = [
            float(row["actual_segment_seconds"])
            for row in rows
        ]

        scheduled_times = [
            float(row["scheduled_segment_seconds"])
            for row in rows
        ]

        incremental_delays = [
            float(row["incremental_delay_seconds"])
            for row in rows
        ]

        measured_speeds = [
            float(row["measured_speed_mph"])
            for row in rows
            if row["measured_speed_mph"] != ""
        ]

        stationary_near = [
            float(row["stationary_near_stop_seconds"])
            for row in rows
        ]

        stationary_away = [
            float(row["stationary_away_from_stop_seconds"])
            for row in rows
        ]

        trip_keys = {
            (
                row["service_date"],
                row["trip_id"],
                row["vehicle_id"],
            )
            for row in rows
        }

        service_dates = {
            row["service_date"]
            for row in rows
        }

        delayed_trip_count = sum(
            delay > 0
            for delay in incremental_delays
        )

        recovered_trip_count = sum(
            delay < 0
            for delay in incremental_delays
        )

        observation_count = len(rows)

        output_rows.append(
            {
                "day_type": day_type,
                "hour_start": hour,
                "hour_end": hour + 1,
                "time_window": (
                    f"{hour:02d}:00-"
                    f"{hour + 1:02d}:00"
                ),
                "segment_from_sequence": from_sequence,
                "segment_to_sequence": to_sequence,
                "segment_from_stop_id": from_stop_id,
                "segment_to_stop_id": to_stop_id,
                "segment_from_stop_name": from_stop_name,
                "segment_to_stop_name": to_stop_name,
                "service_day_count": len(
                    service_dates
                ),
                "trip_count": len(trip_keys),
                "median_actual_seconds": median(
                    actual_times
                ),
                "mean_actual_seconds": mean(
                    actual_times
                ),
                "median_scheduled_seconds": median(
                    scheduled_times
                ),
                "median_incremental_delay_seconds": (
                    median(incremental_delays)
                ),
                "mean_incremental_delay_seconds": (
                    mean(incremental_delays)
                ),
                "delayed_trip_share": round(
                    delayed_trip_count
                    / observation_count,
                    4,
                ),
                "recovered_trip_share": round(
                    recovered_trip_count
                    / observation_count,
                    4,
                ),
                "median_measured_speed_mph": (
                    median(measured_speeds)
                    if measured_speeds
                    else ""
                ),
                "median_stationary_near_stop_seconds": (
                    median(stationary_near)
                ),
                "median_stationary_away_from_stop_seconds": (
                    median(stationary_away)
                ),
            }
        )

    output_rows.sort(
        key=lambda row: (
            row["day_type"],
            row["hour_start"],
            int(row["segment_from_sequence"]),
        )
    )

    if not output_rows:
        raise ValueError(
            "No segment-hour records were created."
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
        f"Segment-hour summaries created: "
        f"{len(output_rows)}"
    )
    print(f"Route key: {route_key}")
    print(f"Output file: {output_file}")


if __name__ == "__main__":
    main()
