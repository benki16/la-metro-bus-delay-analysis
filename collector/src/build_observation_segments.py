import argparse
import csv
import math
from datetime import datetime
from route_analysis_config import enriched_file, load_route_profile, segment_file


ANALYSIS_START_DATE = "20260831"
MIN_STOP_SEQUENCE = 2

# Những khoảng thời gian dài hơn mức này được coi là thiếu coverage.
MAX_VALID_INTERVAL_SECONDS = 60

# Dùng để phát hiện GPS jump bất thường, chưa dùng để phân loại giao thông.
MAX_REASONABLE_SPEED_MPH = 80


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        yield from csv.DictReader(file)


def haversine_distance_m(lat1, lon1, lat2, lon2):
    earth_radius_m = 6_371_000

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2) ** 2
    )

    return 2 * earth_radius_m * math.asin(
        math.sqrt(value)
    )


def parse_timestamp(value):
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-key", default="route70_el_monte")
    arguments = parser.parse_args()
    route_key = arguments.route_key
    profile = load_route_profile(route_key)
    input_file = enriched_file(route_key)
    output_file = segment_file("observations", route_key)
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    observations = []

    for row in read_csv(input_file):
        if row["service_date"] < ANALYSIS_START_DATE:
            continue

        if row["direction_id"] != profile["direction_id"]:
            continue

        if not row["stop_sequence"]:
            continue

        stop_sequence = int(row["stop_sequence"])

        if stop_sequence < MIN_STOP_SEQUENCE:
            continue

        row["_stop_sequence_int"] = stop_sequence
        row["_timestamp_int"] = int(
            row["vehicle_timestamp"]
        )

        observations.append(row)

    observations.sort(
        key=lambda row: (
            row["service_date"],
            row["trip_id"],
            row["vehicle_id"],
            row["_timestamp_int"],
        )
    )

    output_fields = [
        "service_date",
        "trip_id",
        "vehicle_id",
        "observation_time_la",
        "vehicle_timestamp",
        "segment_from_sequence",
        "segment_to_sequence",
        "segment_to_stop_id",
        "segment_to_stop_name",
        "latitude",
        "longitude",
        "current_status",
        "near_target_stop",
        "seconds_since_previous",
        "distance_since_previous_m",
        "calculated_speed_mps",
        "calculated_speed_mph",
        "sequence_change",
        "sequence_gap",
        "observation_quality",
    ]

    output_rows = []

    previous_row = None
    valid_measurements = 0
    sequence_gaps = 0
    time_gaps = 0
    gps_jumps = 0

    for row in observations:
        stop_sequence = row["_stop_sequence_int"]

        output_row = {
            "service_date": row["service_date"],
            "trip_id": row["trip_id"],
            "vehicle_id": row["vehicle_id"],
            "observation_time_la": row[
                "vehicle_time_la"
            ],
            "vehicle_timestamp": row[
                "vehicle_timestamp"
            ],
            "segment_from_sequence": (
                stop_sequence - 1
            ),
            "segment_to_sequence": stop_sequence,
            "segment_to_stop_id": row["stop_id"],
            "segment_to_stop_name": row["stop_name"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "current_status": row["current_status"],
            "near_target_stop": row["within_30m"],
            "seconds_since_previous": "",
            "distance_since_previous_m": "",
            "calculated_speed_mps": "",
            "calculated_speed_mph": "",
            "sequence_change": "",
            "sequence_gap": False,
            "observation_quality": "first_observation",
        }

        same_trip = (
            previous_row is not None
            and previous_row["service_date"]
            == row["service_date"]
            and previous_row["trip_id"]
            == row["trip_id"]
            and previous_row["vehicle_id"]
            == row["vehicle_id"]
        )

        if same_trip:
            previous_sequence = previous_row[
                "_stop_sequence_int"
            ]

            sequence_change = (
                stop_sequence - previous_sequence
            )

            output_row["sequence_change"] = (
                sequence_change
            )

            if sequence_change > 1:
                output_row["sequence_gap"] = True
                output_row[
                    "observation_quality"
                ] = "sequence_gap"
                sequence_gaps += 1

            elif sequence_change < 0:
                output_row[
                    "observation_quality"
                ] = "sequence_regression"

            elif sequence_change == 1:
                output_row[
                    "observation_quality"
                ] = "segment_start"

            else:
                current_time = parse_timestamp(
                    row["vehicle_time_utc"]
                )
                previous_time = parse_timestamp(
                    previous_row["vehicle_time_utc"]
                )

                seconds = (
                    current_time - previous_time
                ).total_seconds()

                output_row[
                    "seconds_since_previous"
                ] = round(seconds, 2)

                if seconds <= 0:
                    output_row[
                        "observation_quality"
                    ] = "invalid_time"

                elif seconds > MAX_VALID_INTERVAL_SECONDS:
                    output_row[
                        "observation_quality"
                    ] = "time_gap"
                    time_gaps += 1

                else:
                    distance_m = haversine_distance_m(
                        float(previous_row["latitude"]),
                        float(previous_row["longitude"]),
                        float(row["latitude"]),
                        float(row["longitude"]),
                    )

                    speed_mps = distance_m / seconds
                    speed_mph = speed_mps * 2.236936

                    output_row[
                        "distance_since_previous_m"
                    ] = round(distance_m, 2)

                    output_row[
                        "calculated_speed_mps"
                    ] = round(speed_mps, 3)

                    output_row[
                        "calculated_speed_mph"
                    ] = round(speed_mph, 2)

                    if speed_mph > MAX_REASONABLE_SPEED_MPH:
                        output_row[
                            "observation_quality"
                        ] = "gps_jump"
                        gps_jumps += 1
                    else:
                        output_row[
                            "observation_quality"
                        ] = "valid"
                        valid_measurements += 1

        output_rows.append(output_row)
        previous_row = row

    with output_file.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=output_fields,
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print(
        f"Input observations retained: "
        f"{len(observations)}"
    )
    print(
        f"Valid movement measurements: "
        f"{valid_measurements}"
    )
    print(f"Sequence gaps: {sequence_gaps}")
    print(f"Time gaps: {time_gaps}")
    print(f"GPS jumps: {gps_jumps}")
    print(f"Route key: {route_key}")
    print(f"Output file: {output_file}")


if __name__ == "__main__":
    main()
