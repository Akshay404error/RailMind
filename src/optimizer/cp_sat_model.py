"""
RailMind - CP-SAT Precedence/Crossing Optimizer

Consumes data/synthetic/section_configs.json (built by generate_synthetic_section.py)
and solves: for every train crossing this corridor, what time should it enter
each block section, such that:
  - safety headway is respected between successive trains on the same section
  - section capacity is respected (1 train at a time for single-line, 2 for double-line)
  - a train can't enter its next section before leaving its current one
while minimizing total priority-weighted delay versus each train's scheduled time.

This is the MVP model: fixed per-section transit duration (from synthetic
speed/length), decision variable = entry time into each section, with a
bounded flexibility window around the scheduled time (holding trains is
allowed; running early beyond a small buffer is not, matching real dispatch
practice).

Output: data/synthetic/optimized_schedule.json — recommended entry time per
train per section, plus per-section precedence order (the actual
"who-goes-first" decision the controller needs).
"""

import json
from pathlib import Path

from ortools.sat.python import cp_model

SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
CONFIG_PATH = SYNTHETIC_DIR / "section_configs.json"
OUTPUT_PATH = SYNTHETIC_DIR / "optimized_schedule.json"

# Priority weight in the objective: higher weight = more costly to delay
PRIORITY_WEIGHT = {1: 3, 2: 2, 3: 1}  # Premium, Express, Passenger

# How far a train's actual entry time can move from its scheduled time.
# EARLY_BUFFER_MIN is 0 on purpose: a train cannot depart/enter a section
# before its scheduled time (that's not a real dispatch option) — it can
# only be HELD later to resolve a conflict. Without this, the solver will
# "solve" every conflict for free by running everything early instead of
# making genuine precedence trade-offs, which is not realistic.
EARLY_BUFFER_MIN = 0
LATE_BUFFER_MIN = 180    # can be held up to 3 hours in this MVP (generous, ensures feasibility)

SOLVER_TIME_LIMIT_SEC = 30


def _time_to_minutes(t):
    if t in (None, "None", "") :
        return None
    try:
        h, m, s = str(t).split(":")
        return int(h) * 60 + int(m) + int(s) / 60
    except (ValueError, AttributeError):
        return None


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_section_durations(sections):
    """Fixed nominal transit duration (minutes) per section, from length/speed."""
    durations = []
    for s in sections:
        length_km = s["length_km"]
        speed = s["max_speed_kmph"]
        duration = max(1, round(length_km / speed * 60))
        durations.append(duration)
    return durations


def build_train_nominal_schedule(train, corridor, section_durations):
    """
    Returns dict: section_index -> nominal absolute entry time (minutes),
    for every section this train traverses (from its first to last corridor
    stop). Forward-fills using actual stop times where known, and
    propagates via nominal section duration through skipped stations.
    """
    known = {}
    for stop in train["stops_on_corridor"]:
        idx = corridor.index(stop["station_code"])
        day = stop.get("day") or 1
        try:
            day = float(day)
        except (TypeError, ValueError):
            day = 1
        t = _time_to_minutes(stop.get("departure")) or _time_to_minutes(stop.get("arrival"))
        if t is not None:
            known[idx] = day * 1440 + t

    if len(known) < 2:
        return {}

    min_idx, max_idx = min(known), max(known)
    nominal_entry = {}
    current_time = known[min_idx]

    for i in range(min_idx, max_idx):
        nominal_entry[i] = current_time
        if (i + 1) in known:
            current_time = known[i + 1]
        else:
            current_time = current_time + section_durations[i]

    return nominal_entry


def solve(config, verbose=True):
    corridor = config["corridor_stations"]
    sections = config["block_sections"]
    section_durations = compute_section_durations(sections)
    section_capacity = [2 if s["line_type"] == "double" else 1 for s in sections]
    section_headway = [s["headway_minutes"] for s in sections]

    model = cp_model.CpModel()

    # entry_vars[(train_number, section_idx)] = IntVar
    entry_vars = {}
    train_nominal = {}   # train_number -> {section_idx: nominal_entry}
    train_priority_weight = {}

    horizon_max = 4 * 1440  # allow up to ~4 simulated days of absolute time range

    for train in config["trains"]:
        nominal = build_train_nominal_schedule(train, corridor, section_durations)
        if not nominal:
            continue  # not enough data to schedule this train, skip

        train_number = train["train_number"]
        train_nominal[train_number] = nominal
        train_priority_weight[train_number] = PRIORITY_WEIGHT.get(train.get("priority_rank", 2), 2)

        for idx, nominal_time in nominal.items():
            lb = max(0, int(nominal_time - EARLY_BUFFER_MIN))
            ub = min(horizon_max, int(nominal_time + LATE_BUFFER_MIN))
            entry_vars[(train_number, idx)] = model.NewIntVar(lb, ub, f"entry_{train_number}_{idx}")

    if not entry_vars:
        raise RuntimeError("No trains had enough schedule data to build a model.")

    # Continuity: within a train's route, can't enter next section before leaving current one
    for train_number, nominal in train_nominal.items():
        indices = sorted(nominal.keys())
        for a, b in zip(indices, indices[1:]):
            if b == a + 1:  # consecutive sections
                duration_a = section_durations[a]
                model.Add(
                    entry_vars[(train_number, b)] >= entry_vars[(train_number, a)] + duration_a
                )

    # Capacity + headway per section, via cumulative resource constraint
    for section_idx in range(len(sections)):
        intervals = []
        demands = []
        for train_number, nominal in train_nominal.items():
            if section_idx not in nominal:
                continue
            entry = entry_vars[(train_number, section_idx)]
            size = section_durations[section_idx] + section_headway[section_idx]
            interval = model.NewFixedSizeIntervalVar(entry, size, f"iv_{train_number}_{section_idx}")
            intervals.append(interval)
            demands.append(1)

        if intervals:
            model.AddCumulative(intervals, demands, section_capacity[section_idx])

    # Objective: minimize total priority-weighted delay at each train's final corridor section
    delay_terms = []
    for train_number, nominal in train_nominal.items():
        last_idx = max(nominal.keys())
        nominal_exit = nominal[last_idx] + section_durations[last_idx]
        actual_exit_expr = entry_vars[(train_number, last_idx)] + section_durations[last_idx]

        # actual_exit can no longer be earlier than nominal_exit (EARLY_BUFFER_MIN=0),
        # so delay is simply the difference — no need to clamp with max(0, ...)
        delay = model.NewIntVar(0, LATE_BUFFER_MIN + 10, f"delay_{train_number}")
        model.Add(delay == actual_exit_expr - int(nominal_exit))

        weight = train_priority_weight[train_number]
        delay_terms.append(weight * delay)

    model.Minimize(sum(delay_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SEC
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)

    if verbose:
        print(f"Solver status: {solver.StatusName(status)}")
        print(f"Trains scheduled: {len(train_nominal)}")
        print(f"Wall time: {solver.WallTime():.2f}s")
        if status == cp_model.FEASIBLE:
            obj = solver.ObjectiveValue()
            bound = solver.BestObjectiveBound()
            gap = (obj - bound) / obj * 100 if obj > 0 else 0.0
            print(f"Objective value: {obj:.0f} (weighted delay-minutes)")
            print(f"Best known bound: {bound:.0f}")
            print(f"Optimality gap: {gap:.1f}% (solution is within this % of the best possible)")
            print("Note: FEASIBLE means a valid, conflict-free schedule was found and is safe to use —")
            print("      it just isn't proven to be the mathematically optimal one within the time limit.")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"Solver failed to find a solution: {solver.StatusName(status)}")

    return solver, entry_vars, train_nominal, section_durations, section_headway, corridor, sections


def build_output(solver, entry_vars, train_nominal, section_durations, corridor, sections):
    schedule = {}
    for train_number, nominal in train_nominal.items():
        schedule[train_number] = []
        for idx in sorted(nominal.keys()):
            entry = solver.Value(entry_vars[(train_number, idx)])
            nominal_entry = nominal[idx]
            schedule[train_number].append({
                "section": f"{sections[idx]['from_station']} -> {sections[idx]['to_station']}",
                "section_index": idx,
                "scheduled_entry_min": round(nominal_entry, 1),
                "recommended_entry_min": entry,
                "delay_min": round(entry - nominal_entry, 1),
            })

    # per-section precedence order (who-goes-first, the actual controller decision)
    precedence = {}
    for idx, section in enumerate(sections):
        section_name = f"{section['from_station']} -> {section['to_station']}"
        occupants = [
            (train_number, solver.Value(entry_vars[(train_number, idx)]))
            for train_number, nominal in train_nominal.items() if idx in nominal
        ]
        occupants.sort(key=lambda x: x[1])
        precedence[section_name] = [
            {"train_number": t, "entry_min": e} for t, e in occupants
        ]

    return {"train_schedules": schedule, "section_precedence": precedence}


def main():
    print("Loading synthetic section config...")
    config = load_config()

    print("Solving precedence/crossing optimization...")
    solver, entry_vars, train_nominal, section_durations, section_headway, corridor, sections = solve(config)

    print("Building output...")
    output = build_output(solver, entry_vars, train_nominal, section_durations, corridor, sections)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Saved optimized schedule -> {OUTPUT_PATH}")

    # quick summary: total delay introduced by the optimizer vs scheduled times
    total_delay = sum(
        entry["delay_min"]
        for train_stops in output["train_schedules"].values()
        for entry in train_stops
        if entry["delay_min"] > 0
    )
    print(f"Total positive delay across all trains/sections: {total_delay:.1f} min")


if __name__ == "__main__":
    main()