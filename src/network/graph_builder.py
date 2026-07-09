"""
RailMind - Network Graph Builder

Builds two things from the raw data:
  1. `network_graph` — a NetworkX DiGraph of the physical rail network.
     Nodes = stations (with lat/long, zone, name).
     Edges = direct station-to-station links actually used by some train,
             weighted by great-circle distance (km) and average travel time (min).
  2. `train_routes` — dict[train_number] -> ordered list of stops
     (station_code, day, arrival, departure), used later to model which
     block sections each train occupies, in order, for the optimizer.

Run directly to build and save both to data/processed/.
"""

import json
import math
import pickle
from pathlib import Path

import pandas as pd
import networkx as nx

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `src.data` import
from data.loader import load_stations, load_schedules  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km between two lat/long points."""
    if any(pd.isna(v) for v in [lat1, lon1, lat2, lon2]):
        return None
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _time_to_minutes(t):
    """Parses 'HH:MM:SS' -> minutes since midnight. Returns None if invalid/missing."""
    if pd.isna(t) or t in (None, "None", ""):
        return None
    try:
        h, m, s = str(t).split(":")
        return int(h) * 60 + int(m) + int(s) / 60
    except (ValueError, AttributeError):
        return None


def build_station_lookup(stations_df: pd.DataFrame) -> dict:
    """station_code -> {name, zone, state, latitude, longitude}"""
    lookup = {}
    for _, row in stations_df.iterrows():
        code = row.get("code")
        if not code or pd.isna(code):
            continue
        lookup[code] = {
            "name": row.get("name"),
            "zone": row.get("zone"),
            "state": row.get("state"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
        }
    return lookup


def build_train_routes(schedules_df: pd.DataFrame) -> dict:
    """
    Groups schedule stops by train_number and orders them by (day, time).
    Uses departure time to sort; falls back to arrival time for the last
    stop (which typically has no departure).
    """
    df = schedules_df.copy()
    df["departure_min"] = df["departure"].apply(_time_to_minutes)
    df["arrival_min"] = df["arrival"].apply(_time_to_minutes)
    df["day"] = pd.to_numeric(df["day"], errors="coerce").fillna(1)

    # sort key: prefer departure time, fall back to arrival time
    df["sort_time"] = df["departure_min"].fillna(df["arrival_min"]).fillna(0)
    df["sort_key"] = df["day"] * 24 * 60 + df["sort_time"]

    routes = {}
    for train_number, group in df.groupby("train_number"):
        group = group.sort_values("sort_key")
        stops = group[["station_code", "station_name", "train_name", "day", "arrival", "departure"]].to_dict("records")

        # drop consecutive duplicate stops (same station code back-to-back) —
        # these are data artifacts (duplicate rows), not real re-visits
        deduped = []
        for stop in stops:
            if deduped and deduped[-1]["station_code"] == stop["station_code"]:
                continue
            deduped.append(stop)

        routes[train_number] = deduped

    return routes


def build_network_graph(station_lookup: dict, train_routes: dict) -> nx.DiGraph:
    """
    Builds a directed graph: an edge (A -> B) exists if some train goes
    directly from station A to station B as consecutive stops.
    Aggregates multiple trains on the same edge (keeps a train count and
    average travel time).
    """
    G = nx.DiGraph()

    # add all known stations as nodes (even if isolated — useful for QA)
    for code, attrs in station_lookup.items():
        G.add_node(code, **attrs)

    for train_number, stops in train_routes.items():
        for i in range(len(stops) - 1):
            a, b = stops[i], stops[i + 1]
            code_a, code_b = a["station_code"], b["station_code"]
            if not code_a or not code_b or pd.isna(code_a) or pd.isna(code_b):
                continue
            if code_a == code_b:
                continue  # self-loop artifact, skip

            # ensure nodes exist even if missing from stations.json
            if code_a not in G:
                G.add_node(code_a, name=a.get("station_name"))
            if code_b not in G:
                G.add_node(code_b, name=b.get("station_name"))

            dep_min = _time_to_minutes(a.get("departure"))
            arr_min = _time_to_minutes(b.get("arrival"))
            day_a, day_b = a.get("day", 1), b.get("day", 1)
            travel_time = None
            if dep_min is not None and arr_min is not None:
                travel_time = (day_b - day_a) * 24 * 60 + (arr_min - dep_min)
                if travel_time is not None and travel_time < 0:
                    travel_time = None  # bad data, discard

            lat_a, lon_a = station_lookup.get(code_a, {}).get("latitude"), station_lookup.get(code_a, {}).get("longitude")
            lat_b, lon_b = station_lookup.get(code_b, {}).get("latitude"), station_lookup.get(code_b, {}).get("longitude")
            dist_km = haversine_km(lat_a, lon_a, lat_b, lon_b)

            if G.has_edge(code_a, code_b):
                edge = G[code_a][code_b]
                edge["train_count"] += 1
                if travel_time is not None:
                    edge["travel_times"].append(travel_time)
            else:
                G.add_edge(
                    code_a, code_b,
                    distance_km=dist_km,
                    train_count=1,
                    travel_times=[travel_time] if travel_time is not None else [],
                )

    # finalize: convert travel_times list -> avg_travel_time_min
    for _, _, edge in G.edges(data=True):
        times = edge.pop("travel_times", [])
        edge["avg_travel_time_min"] = sum(times) / len(times) if times else None

    return G


def main():
    print("Loading stations and schedules...")
    stations_df = load_stations()
    schedules_df = load_schedules()

    print("Building station lookup...")
    station_lookup = build_station_lookup(stations_df)

    print("Building train routes (ordered stops per train)...")
    train_routes = build_train_routes(schedules_df)
    print(f"  {len(train_routes)} distinct trains with route sequences")

    print("Building network graph...")
    G = build_network_graph(station_lookup, train_routes)
    print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Save outputs
    graph_path = PROCESSED_DIR / "network_graph.gpickle"
    routes_path = PROCESSED_DIR / "train_routes.pkl"

    with open(graph_path, "wb") as f:
        pickle.dump(G, f)
    with open(routes_path, "wb") as f:
        pickle.dump(train_routes, f)

    print(f"Saved graph -> {graph_path}")
    print(f"Saved train routes -> {routes_path}")

    # Quick sanity preview
    sample_edges = list(G.edges(data=True))[:5]
    print("\nSample edges:")
    for u, v, d in sample_edges:
        print(f"  {u} -> {v}: {d}")

    # Data quality summary
    edges = list(G.edges(data=True))
    n_edges = len(edges)
    n_missing_dist = sum(1 for _, _, d in edges if d.get("distance_km") is None)
    n_missing_time = sum(1 for _, _, d in edges if d.get("avg_travel_time_min") is None)
    isolated_nodes = list(nx.isolates(G))
    single_stop_trains = sum(1 for stops in train_routes.values() if len(stops) < 2)

    print("\n--- Data quality summary ---")
    print(f"  Edges missing distance (no lat/long on one end): {n_missing_dist}/{n_edges}")
    print(f"  Edges missing travel time (bad/missing timestamps): {n_missing_time}/{n_edges}")
    print(f"  Isolated stations (no schedule uses them): {len(isolated_nodes)}")
    print(f"  Trains with <2 stops after dedup (unusable route): {single_stop_trains}/{len(train_routes)}")


if __name__ == "__main__":
    main()