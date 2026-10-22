import argparse
import csv
from datetime import datetime
from route_analysis_config import segment_file, stop_events_file


MAX_REASONABLE_SEGMENT_SECONDS = 3600

EVENT_QUALITY_RANK = {
    "confirmed_stop": 3,
    "proximity_only": 2,
    "single_observation": 1,
}


def read_csv(path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        yield from csv.DictReader(file)


def parse_datetime(value):
    if not value:
        return None

    return datetime.fromisoformat(value)


def parse_number(value):
    if value in ("", None):
        return None

    return float(value)


def choose_better_event(existing, candidate):
    if existing is None:
        return candidate

    existing_rank = EVENT_QUALITY_RANK.get(
        existing["event_quality"], 0
    )
    candidate_rank = EVENT_QUALITY_RANK.get(
        candidate["event_quality"], 0
    )

    if candidate_rank > existing_rank:
        return candidate

    return existing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-key", default="route70_el_monte")
    arguments = parser.parse_args()
    route_key = arguments.route_key
    segment_states_file = segment_file("states", route_key)
    stop_events_path = stop_events_file(route_key)
    output_file = segment_file("performance", route_key)
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Key: service date + trip + vehicle + stop sequence
    stop_events = {}

    for event in read_csv(stop_events_path):
        key = (
            event["service_date"],
            event["trip_id"],
            event["vehicle_id"],
            int(event["stop_sequence"]),
        )

        stop_events[key] = choose_better_event(
            stop_events.get(key),
            event,
        )

    segment_rows = list(
        read_csv(segment_states_file)
    )

    if not segment_rows:
        raise ValueError(
            "No trip-segment states were found."
        )

    additional_fields = [
        "from_event_quality",
        "to_event_quality",
        "actual_departure_from_stop_la",
        "actual_arrival_to_stop_la",
        "scheduled_departure_from_stop_la",
        "scheduled_arrival_to_stop_la",
        "actual_segment_seconds",
        "scheduled_segment_seconds",
        "incremental_delay_seconds",
        "departure_delay_from_stop_seconds",
        "arrival_delay_to_stop_seconds",
        "delay_change_seconds",
        "formula_difference_seconds",
        "schedule_comparison_quality",
    ]

    output_fields = (
        list(segment_rows[0].keys())
        + additional_fields
    )

    output_rows = []

    valid_comparisons = 0
    missing_stop_events = 0
    zero_schedule_segments = 0
    invalid_actual_segments = 0
    formula_mismatches = 0

    for segment in segment_rows:
        service_date = segment["service_date"]
        trip_id = segment["trip_id"]
        vehicle_id = segment["vehicle_id"]

        from_sequence = int(
            segment["segment_from_sequence"]
        )
        to_sequence = int(
            segment["segment_to_sequence"]
        )

        from_event = stop_events.get(
            (
                service_date,
                trip_id,
                vehicle_id,
                from_sequence,
            )
        )

        to_event = stop_events.get(
            (
                service_date,
                trip_id,
                vehicle_id,
                to_sequence,
            )
        )

        result = dict(segment)

        for field in additional_fields:
            result[field] = ""

        if from_event is None or to_event is None:
            result[
                "schedule_comparison_quality"
            ] = "missing_stop_event"

            missing_stop_events += 1
            output_rows.append(result)
            continue

        result["from_event_quality"] = (
            from_event["event_quality"]
        )
        result["to_event_quality"] = (
            to_event["event_quality"]
        )

        actual_departure = parse_datetime(
            from_event["estimated_departure_la"]
        )
        actual_arrival = parse_datetime(
            to_event["estimated_arrival_la"]
        )

        scheduled_departure = parse_datetime(
            from_event["scheduled_departure_la"]
        )
        scheduled_arrival = parse_datetime(
            to_event["scheduled_arrival_la"]
        )

        result[
            "actual_departure_from_stop_la"
        ] = from_event["estimated_departure_la"]

        result[
            "actual_arrival_to_stop_la"
        ] = to_event["estimated_arrival_la"]

        result[
            "scheduled_departure_from_stop_la"
        ] = from_event["scheduled_departure_la"]

        result[
            "scheduled_arrival_to_stop_la"
        ] = to_event["scheduled_arrival_la"]

        if (
            actual_departure is None
            or actual_arrival is None
        ):
            result[
                "schedule_comparison_quality"
            ] = "missing_actual_time"

            output_rows.append(result)
            continue

        actual_seconds = (
            actual_arrival - actual_departure
        ).total_seconds()

        result["actual_segment_seconds"] = round(
            actual_seconds, 2
        )

        if (
            actual_seconds <= 0
            or actual_seconds
            > MAX_REASONABLE_SEGMENT_SECONDS
        ):
            result[
                "schedule_comparison_quality"
            ] = "invalid_actual_duration"

            invalid_actual_segments += 1
            output_rows.append(result)
            continue

        if (
            scheduled_departure is None
            or scheduled_arrival is None
        ):
            result[
                "schedule_comparison_quality"
            ] = "missing_schedule_time"

            output_rows.append(result)
            continue

        scheduled_seconds = (
            scheduled_arrival
            - scheduled_departure
        ).total_seconds()

        result[
            "scheduled_segment_seconds"
        ] = round(scheduled_seconds, 2)

        departure_delay = parse_number(
            from_event[
                "departure_delay_seconds"
            ]
        )
        arrival_delay = parse_number(
            to_event[
                "arrival_delay_seconds"
            ]
        )

        result[
            "departure_delay_from_stop_seconds"
        ] = (
            round(departure_delay, 2)
            if departure_delay is not None
            else ""
        )

        result[
            "arrival_delay_to_stop_seconds"
        ] = (
            round(arrival_delay, 2)
            if arrival_delay is not None
            else ""
        )

        if scheduled_seconds <= 0:
            result[
                "schedule_comparison_quality"
            ] = "zero_schedule_duration"

            zero_schedule_segments += 1
            output_rows.append(result)
            continue

        incremental_delay = (
            actual_seconds - scheduled_seconds
        )

        result[
            "incremental_delay_seconds"
        ] = round(incremental_delay, 2)

        if (
            departure_delay is not None
            and arrival_delay is not None
        ):
            delay_change = (
                arrival_delay - departure_delay
            )

            formula_difference = (
                incremental_delay - delay_change
            )

            result[
                "delay_change_seconds"
            ] = round(delay_change, 2)

            result[
                "formula_difference_seconds"
            ] = round(formula_difference, 2)

            if abs(formula_difference) > 1:
                result[
                    "schedule_comparison_quality"
                ] = "formula_mismatch"

                formula_mismatches += 1
                output_rows.append(result)
                continue

        result[
            "schedule_comparison_quality"
        ] = "valid"

        valid_comparisons += 1
        output_rows.append(result)

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
        f"Segment-state records read: "
        f"{len(segment_rows)}"
    )
    print(
        f"Valid schedule comparisons: "
        f"{valid_comparisons}"
    )
    print(
        f"Missing stop events: "
        f"{missing_stop_events}"
    )
    print(
        f"Zero scheduled duration: "
        f"{zero_schedule_segments}"
    )
    print(
        f"Invalid actual duration: "
        f"{invalid_actual_segments}"
    )
    print(
        f"Formula mismatches: "
        f"{formula_mismatches}"
    )
    print(f"Route key: {route_key}")
    print(f"Output file: {output_file}")


if __name__ == "__main__":
    main()
