import argparse
import csv
import json
from route_analysis_config import map_files, segment_file, stops_file



def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        yield from csv.DictReader(file)


def classify_traffic(speed_ratio):
    if speed_ratio >= 0.80:
        return "near_best_speed", "#2ecc71"

    if speed_ratio >= 0.60:
        return "moderate_slowdown", "#f1c40f"

    if speed_ratio >= 0.40:
        return "significant_slowdown", "#e67e22"

    return "severe_slowdown", "#e74c3c"


def classify_confidence(service_days, trip_count):
    if service_days >= 7 and trip_count >= 12:
        return "high"

    if service_days >= 5 and trip_count >= 8:
        return "medium"

    return "low"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-key", default="route70_el_monte")
    arguments = parser.parse_args()
    route_key = arguments.route_key
    speed_file = segment_file("speed", route_key)
    schedule_summary_file = segment_file("summary", route_key)
    route_stops_file = stops_file(route_key)
    csv_output, geojson_output = map_files(route_key)
    csv_output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    stops = {}

    for row in read_csv(route_stops_file):
        stops[row["stop_id"]] = {
            "latitude": float(row["stop_lat"]),
            "longitude": float(row["stop_lon"]),
            "name": row["stop_name"],
        }

    schedule_lookup = {}

    for row in read_csv(schedule_summary_file):
        if row["day_type"] != "regular":
            continue

        key = (
            row["time_window"],
            row["segment_from_stop_id"],
            row["segment_to_stop_id"],
        )

        schedule_lookup[key] = row

    map_rows = []
    geojson_features = []
    unmatched_stops = 0

    for row in read_csv(speed_file):
        from_stop_id = row[
            "segment_from_stop_id"
        ]
        to_stop_id = row[
            "segment_to_stop_id"
        ]

        from_stop = stops.get(from_stop_id)
        to_stop = stops.get(to_stop_id)

        if from_stop is None or to_stop is None:
            unmatched_stops += 1
            continue

        speed_ratio = float(row["speed_ratio"])
        service_days = int(
            row["service_day_count"]
        )
        trip_count = int(
            row["hourly_trip_count"]
        )

        traffic_state, color = classify_traffic(
            speed_ratio
        )

        confidence = classify_confidence(
            service_days,
            trip_count,
        )

        schedule_key = (
            row["time_window"],
            from_stop_id,
            to_stop_id,
        )

        schedule_row = schedule_lookup.get(
            schedule_key
        )

        map_row = {
            "time_window": row["time_window"],
            "hour_start": row["hour_start"],
            "hour_end": row["hour_end"],
            "segment_from_sequence": row[
                "segment_from_sequence"
            ],
            "segment_to_sequence": row[
                "segment_to_sequence"
            ],
            "segment_from_stop_id": from_stop_id,
            "segment_to_stop_id": to_stop_id,
            "segment_from_stop_name": row[
                "segment_from_stop_name"
            ],
            "segment_to_stop_name": row[
                "segment_to_stop_name"
            ],
            "from_latitude": from_stop["latitude"],
            "from_longitude": from_stop[
                "longitude"
            ],
            "to_latitude": to_stop["latitude"],
            "to_longitude": to_stop["longitude"],
            "service_day_count": service_days,
            "trip_count": trip_count,
            "p50_hourly_speed_mph": row[
                "p50_hourly_speed_mph"
            ],
            "p80_baseline_speed_mph": row[
                "p80_baseline_speed_mph"
            ],
            "speed_ratio": speed_ratio,
            "traffic_state": traffic_state,
            "color": color,
            "confidence": confidence,
            "median_stationary_share": row[
                "median_stationary_share"
            ],
            "median_stationary_near_seconds": row[
                "median_stationary_near_seconds"
            ],
            "median_stationary_away_seconds": row[
                "median_stationary_away_seconds"
            ],
            "median_actual_seconds": (
                schedule_row[
                    "median_actual_seconds"
                ]
                if schedule_row else ""
            ),
            "median_scheduled_seconds": (
                schedule_row[
                    "median_scheduled_seconds"
                ]
                if schedule_row else ""
            ),
            "median_incremental_delay_seconds": (
                schedule_row[
                    "median_incremental_delay_seconds"
                ]
                if schedule_row else ""
            ),
            "delayed_trip_share": (
                schedule_row["delayed_trip_share"]
                if schedule_row else ""
            ),
            "recovered_trip_share": (
                schedule_row[
                    "recovered_trip_share"
                ]
                if schedule_row else ""
            ),
        }

        map_rows.append(map_row)

        properties = {
            key: value
            for key, value in map_row.items()
            if key not in {
                "from_latitude",
                "from_longitude",
                "to_latitude",
                "to_longitude",
            }
        }

        geojson_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [
                            from_stop["longitude"],
                            from_stop["latitude"],
                        ],
                        [
                            to_stop["longitude"],
                            to_stop["latitude"],
                        ],
                    ],
                },
                "properties": properties,
            }
        )

    if not map_rows:
        raise ValueError(
            "No map records were created."
        )

    map_rows.sort(
        key=lambda row: (
            int(row["hour_start"]),
            int(row["segment_from_sequence"]),
        )
    )

    with csv_output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=map_rows[0].keys(),
        )
        writer.writeheader()
        writer.writerows(map_rows)

    geojson = {
        "type": "FeatureCollection",
        "features": geojson_features,
    }

    with geojson_output.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            geojson,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Map records created: {len(map_rows)}")
    print(f"Unmatched stop records: {unmatched_stops}")
    print(f"Route key: {route_key}")
    print(f"CSV output: {csv_output}")
    print(f"GeoJSON output: {geojson_output}")


if __name__ == "__main__":
    main()
