"""
RailMind - Synthetic Section Generator

Picks a real, busy corridor from the network graph (built by graph_builder.py)
and layers on synthetic block-section parameters that no public dataset
provides: line type (single/double), headways, gradients, signal spacing,
platform counts, and train priority classes.

This is the config the CP-SAT optimizer will actually consume.

Run directly to generate and save data/synthetic/section_configs.json
"""

import json
import pickle
import random
from pathlib import Path

import networkx as nx

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)

random.seed(42)  # reproducible synthetic values

# Priority classes for the optimizer objective (lower number = higher priority)
PRIORITY_RULES = [
    (["rajdhani", "shatabdi", "duronto", "vande bharat"], 1, "Premium"),
    (["express", "mail", "superfast", "sf"], 2, "Express"),
    (["passenger", "local", "mmts", "emu"], 3, "Passenger"),
]
DEFAULT_PRIORITY = (2, "Express")  # fallback if name doesn't match a rule


def load_graph_and_routes():
    with open(PROCESSED_DIR / "network_graph.gpickle", "rb") as f:
        G = pickle.load(f)
    with open(PROCESSED_DIR / "train_routes.pkl", "rb") as f:
        train_routes = pickle.load(f)
    return G, train_routes


def find_busiest_corridor(G: nx.DiGraph, target_length: int = 8) -> list:
    """
    Greedily walks the graph starting from the busiest edge (highest
    train_count), extending in whichever direction has the busiest
    unvisited neighbor, until target_length stations are collected.
    This gives a real, high-traffic corridor rather than an arbitrary one.
    """
    if G.number_of_edges() == 0:
        raise ValueError("Graph has no edges — run graph_builder.py first.")

    busiest_edge = max(G.edges(data=True), key=lambda e: e[2].get("train_count", 0))
    corridor = [busiest_edge[0], busiest_edge[1]]
    visited = set(corridor)

    while len(corridor) < target_length:
        extended = False

        # try extending forward from the last station
        neighbors = [(n, G[corridor[-1]][n].get("train_count", 0))
                     for n in G.successors(corridor[-1]) if n not in visited]
        if neighbors:
            best = max(neighbors, key=lambda x: x[1])[0]
            corridor.append(best)
            visited.add(best)
            extended = True

        if len(corridor) >= target_length:
            break

        # try extending backward from the first station
        neighbors = [(n, G[n][corridor[0]].get("train_count", 0))
                     for n in G.predecessors(corridor[0]) if n not in visited]
        if neighbors:
            best = max(neighbors, key=lambda x: x[1])[0]
            corridor.insert(0, best)
            visited.add(best)
            extended = True

        if not extended:
            break  # dead end, stop with what we have

    return corridor


def classify_priority(train_name: str):
    name = (train_name or "").lower()
    for keywords, rank, label in PRIORITY_RULES:
        if any(kw in name for kw in keywords):
            return rank, label
    return DEFAULT_PRIORITY


def synthesize_block_section(distance_km, avg_travel_time_min, train_count):
    """
    Generates plausible operational parameters for one block section.
    Busier sections (more trains historically) are more likely to be
    double-line with tighter headways; quieter ones single-line.
    """
    distance_km = distance_km if distance_km else round(random.uniform(5, 15), 1)
    is_double_line = train_count >= 3 or random.random() < 0.4

    return {
        "length_km": round(distance_km, 2),
        "line_type": "double" if is_double_line else "single",
        "max_speed_kmph": random.choice([80, 100, 110, 130]) if is_double_line else random.choice([60, 80]),
        "headway_minutes": random.choice([3, 4, 5]) if is_double_line else random.choice([7, 10, 15]),
        "gradient_percent": round(random.uniform(0.0, 1.2), 2),
        "signal_spacing_km": round(random.uniform(1.0, 2.5), 2),
        "historical_train_count": train_count,
        "avg_observed_travel_time_min": round(avg_travel_time_min, 1) if avg_travel_time_min else None,
    }


def synthesize_platforms(station_code: str) -> int:
    # major junctions (high train_count already reflected in corridor selection)
    # get more platforms; keep it simple and reproducible
    random.seed(hash(station_code) % (2**32))
    return random.choice([2, 2, 3, 3, 4, 5])


def collect_trains_on_corridor(train_routes: dict, corridor: list) -> list:
    """
    Finds trains whose route includes two or more consecutive corridor
    stations, in the same order — i.e., trains that actually use this
    corridor (or part of it).
    """
    corridor_set = corridor
    trains_on_corridor = []

    for train_number, stops in train_routes.items():
        codes = [s["station_code"] for s in stops]
        # find longest overlapping consecutive match with corridor order
        matched_indices = [i for i, c in enumerate(codes) if c in corridor_set]
        if len(matched_indices) < 2:
            continue

        matched_codes = [codes[i] for i in matched_indices]
        # check the matched stations appear in the same relative order as the corridor
        corridor_positions = [corridor_set.index(c) for c in matched_codes]
        if corridor_positions == sorted(corridor_positions) and len(set(corridor_positions)) >= 2:
            train_name = stops[matched_indices[0]].get("train_name")
            trains_on_corridor.append({
                "train_number": train_number,
                "train_name": train_name,
                "stops_on_corridor": [
                    {"station_code": codes[i], "arrival": stops[i].get("arrival"),
                     "departure": stops[i].get("departure"), "day": stops[i].get("day")}
                    for i in matched_indices
                ],
            })

    return trains_on_corridor


def main(target_length: int = 8):
    print("Loading graph and train routes...")
    G, train_routes = load_graph_and_routes()

    print(f"Finding busiest corridor (target {target_length} stations)...")
    corridor = find_busiest_corridor(G, target_length)
    print(f"  Corridor: {' -> '.join(corridor)}")

    print("Synthesizing block-section parameters...")
    sections = []
    for i in range(len(corridor) - 1):
        a, b = corridor[i], corridor[i + 1]
        edge = G.get_edge_data(a, b) or {}
        section = synthesize_block_section(
            edge.get("distance_km"),
            edge.get("avg_travel_time_min"),
            edge.get("train_count", 0),
        )
        section["from_station"] = a
        section["to_station"] = b
        sections.append(section)

    print("Synthesizing platform counts...")
    platforms = {code: synthesize_platforms(code) for code in corridor}

    print("Collecting real trains that use this corridor...")
    trains_on_corridor = collect_trains_on_corridor(train_routes, corridor)
    for t in trains_on_corridor:
        t["priority_rank"], t["priority_label"] = classify_priority(t.get("train_name"))

    print(f"  {len(trains_on_corridor)} trains found using this corridor")

    config = {
        "corridor_stations": corridor,
        "block_sections": sections,
        "platforms": platforms,
        "trains": trains_on_corridor,
    }

    out_path = SYNTHETIC_DIR / "section_configs.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)

    print(f"\nSaved synthetic section config -> {out_path}")
    print(f"Sections: {len(sections)} | Stations: {len(corridor)} | Trains: {len(trains_on_corridor)}")


if __name__ == "__main__":
    main()