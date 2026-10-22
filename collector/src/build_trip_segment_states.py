import argparse
import csv
from collections import defaultdict
from datetime import datetime
from route_analysis_config import segment_file


# Tốc độ dưới hoặc bằng mức này được xem là gần như đứng yên.
STATIONARY_SPEED_MPH = 1.0

VALID_QUALITIES = {"valid", "gps_jump", "time_gap"}

# Bắt đầu phân tích từ segment 2 → 3.
MIN_FROM_SEQUENCE = 2


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        yield from csv.DictReader(file)


def parse_boolean(value):
    return str(value).strip().lower() == "true"


def parse_datetime(value):
    return datetime.fromisoformat(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-key", default="route70_el_monte")
    arguments = parser.parse_args()
    route_key = arguments.route_key
    input_file = segment_file("observations", route_key)
    output_file = segment_file("states", route_key)
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    groups = defaultdict(list)
    stop_lookup = {}

    for row in read_csv(input_file):
        from_sequence = int(
            row["segment_from_sequence"]
        )
        to_sequence = int(
            row["segment_to_sequence"]
        )

        stop_lookup[
            (
                row["service_date"],
                row["trip_id"],
                to_sequence,
            )
        ] = {
            "stop_id": row["segment_to_stop_id"],
            "stop_name": row["segment_to_stop_name"],
        }

        # Loại segment 1 → 2 khỏi phân tích chính.
        if from_sequence < MIN_FROM_SEQUENCE:
            continue

        key = (
            row["service_date"],
            row["trip_id"],
            row["vehicle_id"],
            from_sequence,
            to_sequence,
        )

        groups[key].append(row)

    output_rows = []

    for key, rows in groups.items():
        (
            service_date,
            trip_id,
            vehicle_id,
            from_sequence,
            to_sequence,
        ) = key

        rows.sort(
            key=lambda row: int(
                row["vehicle_timestamp"]
            )
        )

        first_time = parse_datetime(
            rows[0]["observation_time_la"]
        )
        last_time = parse_datetime(
            rows[-1]["observation_time_la"]
        )

        observed_span_seconds = (
            last_time - first_time
        ).total_seconds()

        valid_observation_count = 0
        measured_seconds = 0.0
        measured_distance_m = 0.0

        stationary_seconds = 0.0
        stationary_near_stop_seconds = 0.0
        stationary_away_from_stop_seconds = 0.0

        gps_jump_count = 0
        time_gap_count = 0
        sequence_gap_count = 0

        segment_start_observed = False

        for row in rows:
            quality = row["observation_quality"]

            if quality == "segment_start":
                segment_start_observed = True

            if quality == "gps_jump":
                gps_jump_count += 1
                continue

            if quality == "time_gap":
                time_gap_count += 1
                continue

            if quality == "sequence_gap":
                sequence_gap_count += 1
                continue

            if quality != "valid":
                continue

            seconds_value = row[
                "seconds_since_previous"
            ]
            distance_value = row[
                "distance_since_previous_m"
            ]
            speed_value = row[
                "calculated_speed_mph"
            ]

            if (
                not seconds_value
                or not distance_value
                or not speed_value
            ):
                # Distance và speed có thể bằng 0 dưới dạng "0.0",
                # nên chỉ chuỗi rỗng mới bị loại.
                if seconds_value == "":
                    continue
                if distance_value == "":
                    continue
                if speed_value == "":
                    continue

            seconds = float(seconds_value)
            distance_m = float(distance_value)
            speed_mph = float(speed_value)

            valid_observation_count += 1
            measured_seconds += seconds
            measured_distance_m += distance_m

            if speed_mph <= STATIONARY_SPEED_MPH:
                stationary_seconds += seconds

                if parse_boolean(
                    row["near_target_stop"]
                ):
                    stationary_near_stop_seconds += (
                        seconds
                    )
                else:
                    stationary_away_from_stop_seconds += (
                        seconds
                    )

        if measured_seconds > 0:
            measured_speed_mps = (
                measured_distance_m
                / measured_seconds
            )
            measured_speed_mph = (
                measured_speed_mps * 2.236936
            )

            stationary_share = (
                stationary_seconds
                / measured_seconds
            )

            measurement_coverage = (
                measured_seconds
                / observed_span_seconds
                if observed_span_seconds > 0
                else 0
            )
        else:
            measured_speed_mph = None
            stationary_share = None
            measurement_coverage = 0

        from_stop = stop_lookup.get(
            (
                service_date,
                trip_id,
                from_sequence,
            ),
            {},
        )

        to_stop = stop_lookup.get(
            (
                service_date,
                trip_id,
                to_sequence,
            ),
            {},
        )

        next_segment_exists = (
            service_date,
            trip_id,
            to_sequence + 1,
        ) in stop_lookup

        if (
            segment_start_observed
            and next_segment_exists
            and valid_observation_count >= 2
            and measurement_coverage >= 0.50
        ):
            segment_quality = "good"
        elif valid_observation_count >= 2:
            segment_quality = "partial"
        else:
            segment_quality = "insufficient"

        output_rows.append(
            {
                "service_date": service_date,
                "trip_id": trip_id,
                "vehicle_id": vehicle_id,
                "segment_from_sequence": from_sequence,
                "segment_to_sequence": to_sequence,
                "segment_from_stop_id": from_stop.get(
                    "stop_id", ""
                ),
                "segment_from_stop_name": from_stop.get(
                    "stop_name", ""
                ),
                "segment_to_stop_id": to_stop.get(
                    "stop_id", ""
                ),
                "segment_to_stop_name": to_stop.get(
                    "stop_name", ""
                ),
                "segment_observation_start_la": (
                    rows[0]["observation_time_la"]
                ),
                "segment_observation_end_la": (
                    rows[-1]["observation_time_la"]
                ),
                "observed_span_seconds": round(
                    observed_span_seconds, 2
                ),
                "measured_seconds": round(
                    measured_seconds, 2
                ),
                "measured_distance_m": round(
                    measured_distance_m, 2
                ),
                "measured_speed_mph": (
                    round(measured_speed_mph, 2)
                    if measured_speed_mph is not None
                    else ""
                ),
                "stationary_seconds": round(
                    stationary_seconds, 2
                ),
                "stationary_near_stop_seconds": round(
                    stationary_near_stop_seconds, 2
                ),
                "stationary_away_from_stop_seconds": round(
                    stationary_away_from_stop_seconds, 2
                ),
                "stationary_share": (
                    round(stationary_share, 4)
                    if stationary_share is not None
                    else ""
                ),
                "observation_count": len(rows),
                "valid_observation_count": (
                    valid_observation_count
                ),
                "measurement_coverage": round(
                    measurement_coverage, 4
                ),
                "gps_jump_count": gps_jump_count,
                "time_gap_count": time_gap_count,
                "sequence_gap_count": (
                    sequence_gap_count
                ),
                "segment_start_observed": (
                    segment_start_observed
                ),
                "segment_end_observed": (
                    next_segment_exists
                ),
                "segment_quality": segment_quality,
            }
        )

    output_rows.sort(
        key=lambda row: (
            row["service_date"],
            row["trip_id"],
            row["vehicle_id"],
            row["segment_from_sequence"],
        )
    )

    fieldnames = list(output_rows[0].keys())

    if not output_rows:
        raise ValueError("No trip-segment records were created.")

    with output_file.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(output_rows)

    print(
        f"Trip-segment records created: "
        f"{len(output_rows)}"
    )
    print(f"Route key: {route_key}")
    print(f"Output file: {output_file}")


if __name__ == "__main__":
    main()
