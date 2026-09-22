from collections import Counter
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen
from streamlit_folium import st_folium


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ROUTES = {
    "route70_el_monte": {
        "label": "Route 70 — Downtown LA to El Monte",
        "route_code": "70",
        "map_file": (
            PROJECT_ROOT
            / "data"
            / "processed"
            / "map"
            / "route70_el_monte_map_data.csv"
        ),
        "route_directory": (
            PROJECT_ROOT
            / "data"
            / "processed"
            / "route70"
        ),
        "stop_times_filename": "stop_times_direction_0.csv",
        "stops_filename": "stops_direction_0.csv",
        "fallback_color": "#2563eb",
    },
    "route76_el_monte": {
        "label": "Route 76 — Downtown LA to El Monte",
        "route_code": "76",
        "map_file": (
            PROJECT_ROOT
            / "data"
            / "processed"
            / "map"
            / "route76_el_monte_map_data.csv"
        ),
        "route_directory": (
            PROJECT_ROOT
            / "data"
            / "processed"
            / "routes"
            / "route76_el_monte"
        ),
        "stop_times_filename": "stop_times.csv",
        "stops_filename": "stops.csv",
        "fallback_color": "#7c3aed",
    },
    "route268_el_monte": {
        "label": "Route 268 — Sierra Madre Villa to El Monte",
        "route_code": "268",
        "map_file": (
            PROJECT_ROOT
            / "data"
            / "processed"
            / "map"
            / "route268_el_monte_map_data.csv"
        ),
        "route_directory": (
            PROJECT_ROOT
            / "data"
            / "processed"
            / "routes"
            / "route268_el_monte"
        ),
        "stop_times_filename": "stop_times.csv",
        "stops_filename": "stops.csv",
        "fallback_color": "#0f766e",
    },
}

TRAFFIC_LABELS = {
    "near_best_speed": "Near best speed",
    "moderate_slowdown": "Moderate slowdown",
    "significant_slowdown": "Significant slowdown",
    "severe_slowdown": "Severe slowdown",
}

NUMERIC_COLUMNS = [
    "hour_start",
    "hour_end",
    "segment_from_sequence",
    "segment_to_sequence",
    "from_latitude",
    "from_longitude",
    "to_latitude",
    "to_longitude",
    "service_day_count",
    "trip_count",
    "p50_hourly_speed_mph",
    "p80_baseline_speed_mph",
    "speed_ratio",
    "median_stationary_share",
    "median_stationary_near_seconds",
    "median_stationary_away_seconds",
    "median_actual_seconds",
    "median_scheduled_seconds",
    "median_incremental_delay_seconds",
]


def format_number(value, decimals=1, suffix=""):
    if pd.isna(value) or value == "":
        return "Not available"

    return f"{float(value):.{decimals}f}{suffix}"


def route_label(route_key):
    return ROUTES[route_key]["label"]


@st.cache_data
def load_map_data(route_key):
    map_file = ROUTES[route_key]["map_file"]

    if not map_file.exists():
        return pd.DataFrame()

    data = pd.read_csv(map_file)

    for column in NUMERIC_COLUMNS:
        if column in data.columns:
            data[column] = pd.to_numeric(
                data[column],
                errors="coerce",
            )

    data["route_key"] = route_key
    data["route_label"] = route_label(route_key)
    data["traffic_label"] = data["traffic_state"].map(
        TRAFFIC_LABELS
    )

    return data


@st.cache_data
def load_route_stops(route_key):
    """Return the most common scheduled stop pattern for one route profile."""
    config = ROUTES[route_key]
    route_directory = config["route_directory"]
    stop_times_file = route_directory / config["stop_times_filename"]
    stops_file = route_directory / config["stops_filename"]

    if not stop_times_file.exists() or not stops_file.exists():
        return pd.DataFrame()

    stop_times = pd.read_csv(
        stop_times_file,
        dtype={"trip_id": str, "stop_id": str},
    )
    stops = pd.read_csv(stops_file, dtype={"stop_id": str})

    stop_times["stop_sequence"] = pd.to_numeric(
        stop_times["stop_sequence"],
        errors="coerce",
    )
    stop_times = stop_times.dropna(subset=["stop_sequence"])
    stop_times = stop_times.sort_values(
        ["trip_id", "stop_sequence"]
    )

    patterns = {}
    for trip_id, trip_rows in stop_times.groupby("trip_id"):
        patterns[trip_id] = tuple(trip_rows["stop_id"].tolist())

    if not patterns:
        return pd.DataFrame()

    canonical_pattern = Counter(patterns.values()).most_common(1)[0][0]
    canonical_trip_id = next(
        trip_id
        for trip_id, pattern in patterns.items()
        if pattern == canonical_pattern
    )

    route_stops = stop_times[
        stop_times["trip_id"] == canonical_trip_id
    ].copy()
    route_stops = route_stops.merge(
        stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
        how="left",
        on="stop_id",
    )
    route_stops["stop_lat"] = pd.to_numeric(
        route_stops["stop_lat"],
        errors="coerce",
    )
    route_stops["stop_lon"] = pd.to_numeric(
        route_stops["stop_lon"],
        errors="coerce",
    )

    return route_stops.dropna(
        subset=["stop_lat", "stop_lon"]
    ).sort_values("stop_sequence")


def create_stop_table(filtered_data):
    stops = {}

    for _, row in filtered_data.iterrows():
        from_id = str(row["segment_from_stop_id"])
        to_id = str(row["segment_to_stop_id"])

        stops[from_id] = {
            "stop_id": from_id,
            "sequence": int(row["segment_from_sequence"]),
            "name": row["segment_from_stop_name"],
            "latitude": row["from_latitude"],
            "longitude": row["from_longitude"],
        }
        stops[to_id] = {
            "stop_id": to_id,
            "sequence": int(row["segment_to_sequence"]),
            "name": row["segment_to_stop_name"],
            "latitude": row["to_latitude"],
            "longitude": row["to_longitude"],
        }

    return sorted(stops.values(), key=lambda stop: stop["sequence"])


def add_static_route(route_map, route_key, route_stops, show_stop_names):
    """Draw a route with neutral lines while operational data are unavailable."""
    if route_stops.empty:
        return

    config = ROUTES[route_key]
    locations = route_stops[["stop_lat", "stop_lon"]].values.tolist()

    folium.PolyLine(
        locations=locations,
        color=config["fallback_color"],
        weight=5,
        opacity=0.65,
        dash_array="8, 8",
        tooltip=(
            f'{config["label"]} — static route; '
            "performance data pending"
        ),
    ).add_to(route_map)

    terminal_sequences = {
        int(route_stops["stop_sequence"].min()),
        int(route_stops["stop_sequence"].max()),
    }

    for _, stop in route_stops.iterrows():
        sequence = int(stop["stop_sequence"])
        is_terminal = sequence in terminal_sequences
        marker = folium.CircleMarker(
            location=[stop["stop_lat"], stop["stop_lon"]],
            radius=6 if is_terminal else 3,
            color=config["fallback_color"],
            weight=1.2,
            fill=True,
            fill_color="#ffffff" if not is_terminal else config["fallback_color"],
            fill_opacity=1,
        )
        marker.add_child(
            folium.Tooltip(
                f'{config["route_code"]} · {sequence}. {stop["stop_name"]}',
                permanent=show_stop_names,
                direction="top" if sequence % 2 == 0 else "bottom",
                sticky=False,
            )
        )
        marker.add_child(
            folium.Popup(
                f'<b>Route {config["route_code"]} · Stop {sequence}</b><br>'
                f'{stop["stop_name"]}<br>'
                f'Stop ID: {stop["stop_id"]}',
                max_width=280,
            )
        )
        marker.add_to(route_map)


def add_condition_segments(route_map, filtered_data, route_key):
    opacity_lookup = {"high": 0.95, "medium": 0.72, "low": 0.45}
    route_code = ROUTES[route_key]["route_code"]

    for _, row in filtered_data.iterrows():
        popup_html = f"""
        <div style="width:310px">
            <h4 style="margin:0 0 8px 0;">
                Route {route_code} · Segment
                {int(row["segment_from_sequence"])} →
                {int(row["segment_to_sequence"])}
            </h4>
            <b>From:</b> {row["segment_from_stop_name"]}<br>
            <b>To:</b> {row["segment_to_stop_name"]}<br><br>
            <b>Time window:</b> {row["time_window"]}<br>
            <b>Condition:</b> {row["traffic_label"]}<br>
            <b>P50 hourly speed:</b>
            {format_number(row["p50_hourly_speed_mph"], 1, " mph")}<br>
            <b>P80 baseline speed:</b>
            {format_number(row["p80_baseline_speed_mph"], 1, " mph")}<br>
            <b>Speed ratio:</b>
            {format_number(row["speed_ratio"] * 100, 1, "%")}<br><br>
            <b>Median incremental delay:</b>
            {format_number(row["median_incremental_delay_seconds"], 1, " sec")}<br>
            <b>Trips:</b> {int(row["trip_count"])}<br>
            <b>Service days:</b> {int(row["service_day_count"])}<br>
            <b>Confidence:</b> {row["confidence"].title()}
        </div>
        """

        folium.PolyLine(
            locations=[
                [row["from_latitude"], row["from_longitude"]],
                [row["to_latitude"], row["to_longitude"]],
            ],
            color=row["color"],
            weight=8,
            opacity=opacity_lookup.get(row["confidence"], 0.50),
            tooltip=(
                f'Route {route_code} | '
                f'{int(row["segment_from_sequence"])} → '
                f'{int(row["segment_to_sequence"])} | '
                f'{row["traffic_label"]}'
            ),
            popup=folium.Popup(popup_html, max_width=350),
        ).add_to(route_map)


def add_condition_stops(route_map, filtered_data, route_key, show_stop_names):
    stops = create_stop_table(filtered_data)
    if not stops:
        return

    terminal_sequences = {
        min(stop["sequence"] for stop in stops),
        max(stop["sequence"] for stop in stops),
    }
    route_code = ROUTES[route_key]["route_code"]

    for stop in stops:
        is_terminal = stop["sequence"] in terminal_sequences
        marker = folium.CircleMarker(
            location=[stop["latitude"], stop["longitude"]],
            radius=6 if is_terminal else 3.5,
            color="#111827",
            weight=1.5,
            fill=True,
            fill_color="#ffffff" if not is_terminal else "#2563eb",
            fill_opacity=1,
        )
        marker.add_child(
            folium.Tooltip(
                f'Route {route_code} · {stop["sequence"]}. {stop["name"]}',
                permanent=show_stop_names,
                direction="top" if stop["sequence"] % 2 == 0 else "bottom",
                sticky=False,
            )
        )
        marker.add_child(
            folium.Popup(
                f'<b>Route {route_code} · Stop {stop["sequence"]}</b><br>'
                f'{stop["name"]}<br>Stop ID: {stop["stop_id"]}',
                max_width=280,
            )
        )
        marker.add_to(route_map)


def build_map(
    filtered_data,
    route_stops_by_key,
    selected_routes,
    available_performance_routes,
    show_stop_names,
):
    all_locations = []
    for route_key in selected_routes:
        route_stops = route_stops_by_key.get(route_key)
        if route_stops is not None and not route_stops.empty:
            all_locations.extend(
                route_stops[["stop_lat", "stop_lon"]].values.tolist()
            )

    if not all_locations and not filtered_data.empty:
        all_locations.extend(
            filtered_data[["from_latitude", "from_longitude"]].values.tolist()
        )
        all_locations.extend(
            filtered_data[["to_latitude", "to_longitude"]].values.tolist()
        )

    if not all_locations:
        return None

    center_latitude = sum(location[0] for location in all_locations) / len(all_locations)
    center_longitude = sum(location[1] for location in all_locations) / len(all_locations)
    route_map = folium.Map(
        location=[center_latitude, center_longitude],
        zoom_start=11,
        tiles="CartoDB positron",
        control_scale=True,
    )
    Fullscreen(
        position="topleft",
        title="Full screen",
        title_cancel="Exit full screen",
    ).add_to(route_map)

    # Draw routes with no processed performance data first.
    for route_key in selected_routes:
        if route_key not in available_performance_routes:
            add_static_route(
                route_map,
                route_key,
                route_stops_by_key[route_key],
                show_stop_names,
            )

    # Draw colored observed conditions above the static network.
    for route_key in selected_routes:
        route_segments = filtered_data[
            filtered_data["route_key"] == route_key
        ]
        if route_segments.empty:
            continue
        add_condition_segments(route_map, route_segments, route_key)
        add_condition_stops(
            route_map,
            route_segments,
            route_key,
            show_stop_names,
        )

    route_map.fit_bounds(all_locations, padding=(25, 25))

    pending_routes = [
        f'Route {ROUTES[key]["route_code"]}'
        for key in selected_routes
        if key not in available_performance_routes
    ]
    pending_line = (
        "<br><small>Dashed route: performance data pending for "
        + ", ".join(pending_routes)
        + "</small>"
        if pending_routes
        else ""
    )

    legend_html = f"""
    <div style="
        position: fixed; left: 25px; bottom: 30px; z-index: 9999;
        background: rgba(255,255,255,0.95); border: 1px solid #9ca3af;
        border-radius: 7px; padding: 12px 15px; font-size: 13px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.18);">
        <b>Observed speed condition</b><br>
        <span style="color:#2ecc71">●</span> Near best speed (≥80%)<br>
        <span style="color:#f1c40f">●</span> Moderate slowdown (60–80%)<br>
        <span style="color:#e67e22">●</span> Significant slowdown (40–60%)<br>
        <span style="color:#e74c3c">●</span> Severe slowdown (&lt;40%)<br>
        <small>Compared with each segment's P80 speed.</small>
        {pending_line}
    </div>
    """
    route_map.get_root().html.add_child(folium.Element(legend_html))
    return route_map


st.set_page_config(
    page_title="LA Metro Bus Conditions",
    page_icon="🚌",
    layout="wide",
)

st.title("LA Metro Bus Speed Conditions")
st.caption(
    "Weekday service toward El Monte · Study window: 2:00–8:00 PM · "
    "Map values aggregate the selected study period."
)

control_1, control_2 = st.columns([2.2, 1])
with control_1:
    selected_routes = st.multiselect(
        "Routes displayed",
        options=list(ROUTES),
        default=list(ROUTES),
        format_func=route_label,
    )
with control_2:
    show_stop_names = st.toggle("Show stop names", value=False)

if not selected_routes:
    st.info("Select at least one route to display the map.")
    st.stop()

route_stops_by_key = {
    route_key: load_route_stops(route_key)
    for route_key in selected_routes
}
all_data = pd.concat(
    [
        load_map_data(route_key)
        for route_key in selected_routes
        if not load_map_data(route_key).empty
    ],
    ignore_index=True,
) if any(
    not load_map_data(route_key).empty
    for route_key in selected_routes
) else pd.DataFrame()

available_performance_routes = set(all_data.get("route_key", []))
pending_labels = [
    route_label(route_key)
    for route_key in selected_routes
    if route_key not in available_performance_routes
]

if pending_labels:
    st.info(
        "Static route and stops are shown for: "
        + "; ".join(pending_labels)
        + ". Their speed colors will appear automatically after "
        "the route-specific processing pipeline produces map data."
    )

if all_data.empty:
    st.warning("No processed performance data are available yet.")
    filtered = pd.DataFrame()
else:
    available_hours = sorted(all_data["time_window"].dropna().unique())
    control_3, control_4, control_5 = st.columns([1.3, 2.0, 1.4])
    with control_3:
        selected_hour = st.selectbox(
            "Time window",
            available_hours,
            index=(available_hours.index("17:00-18:00") if "17:00-18:00" in available_hours else 0),
        )
    with control_4:
        selected_states = st.multiselect(
            "Traffic condition",
            options=list(TRAFFIC_LABELS),
            default=list(TRAFFIC_LABELS),
            format_func=lambda value: TRAFFIC_LABELS[value],
        )
    with control_5:
        selected_confidence = st.multiselect(
            "Confidence",
            options=["high", "medium", "low"],
            default=["high", "medium"],
            format_func=str.title,
        )

    filtered = all_data[
        (all_data["time_window"] == selected_hour)
        & all_data["traffic_state"].isin(selected_states)
        & all_data["confidence"].isin(selected_confidence)
    ].copy()

metric_1, metric_2, metric_3, metric_4 = st.columns(4)
if filtered.empty:
    metric_1.metric("Segments displayed", "0")
    metric_2.metric("Severe slowdowns", "0")
    metric_3.metric("Median speed ratio", "—")
    metric_4.metric("High-confidence coverage", "—")
else:
    metric_1.metric("Segments displayed", f"{len(filtered)}")
    metric_2.metric(
        "Severe slowdowns",
        f'{(filtered["traffic_state"] == "severe_slowdown").sum()}',
    )
    metric_3.metric(
        "Median speed ratio",
        f'{filtered["speed_ratio"].median():.0%}',
    )
    metric_4.metric(
        "High-confidence coverage",
        f'{(filtered["confidence"] == "high").mean():.0%}',
    )

map_column, detail_column = st.columns([4.2, 1.2])
with map_column:
    route_map = build_map(
        filtered,
        route_stops_by_key,
        selected_routes,
        available_performance_routes,
        show_stop_names,
    )
    if route_map is None:
        st.error("The selected routes do not yet have usable stop coordinates.")
    else:
        st_folium(
            route_map,
            height=680,
            use_container_width=True,
            returned_objects=[],
        )

with detail_column:
    st.subheader("Segment details")
    if filtered.empty:
        st.caption("No observed segments match the current filters.")
    else:
        filtered["segment_label"] = (
            "Route "
            + filtered["route_key"].map(lambda key: ROUTES[key]["route_code"])
            + " | "
            + filtered["segment_from_sequence"].astype(int).astype(str)
            + " → "
            + filtered["segment_to_sequence"].astype(int).astype(str)
            + " | "
            + filtered["segment_from_stop_name"]
        )
        selected_segment = st.selectbox(
            "Select segment",
            filtered["segment_label"].tolist(),
        )
        selected_row = filtered[
            filtered["segment_label"] == selected_segment
        ].iloc[0]
        st.markdown(
            f"""
            **From**  
            {selected_row["segment_from_stop_name"]}

            **To**  
            {selected_row["segment_to_stop_name"]}

            **Traffic condition**  
            {selected_row["traffic_label"]}

            **P50 / P80 speed**  
            {format_number(selected_row["p50_hourly_speed_mph"], 1, " mph")} /
            {format_number(selected_row["p80_baseline_speed_mph"], 1, " mph")}

            **Median incremental delay**  
            {format_number(selected_row["median_incremental_delay_seconds"], 1, " seconds")}

            **Trips / service days**  
            {int(selected_row["trip_count"])} trips across
            {int(selected_row["service_day_count"])} days

            **Confidence**  
            {selected_row["confidence"].title()}
            """
        )

st.caption(
    "Colors represent hourly P50 speed relative to each segment's P80 "
    "observed speed. They show operating conditions, not confirmed causes "
    "of roadway congestion."
)
