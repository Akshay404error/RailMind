# Architecture

## System overview

```
Raw data (stations, trains, schedules, delays)
        │
        ▼
  src/data/loader.py ─────────► pandas DataFrames
        │
        ▼
  src/network/graph_builder.py ──► NetworkX DiGraph (stations + block sections)
        │
        ▼
  src/data/generate_synthetic_section.py ──► data/synthetic/section_configs.json
        │                                     (a chosen corridor: stations, block
        │                                      sections with line_type/headway/
        │                                      capacity, trains with stop times
        │                                      and priority ranks)
        ▼
  src/optimizer/cp_sat_model.py ──► data/synthetic/optimized_schedule.json
        │                            (recommended entry_min per train per section
        │                             + section precedence order)
        ▼
  src/simulator/schedule_simulator.py
        │  - independently re-verifies the plan is conflict-free
        │  - supports injecting a delay and checking what breaks
        ▼
  src/rl/environment_v2.py + train_qlearning_v2.py
        │  - wraps the simulator as a disruption-response environment
        │  - trains/evaluates a policy for "which train to hold" decisions
        ▼
  src/rl/diagnose_gaveup.py
        │  - traces unresolved episodes to classify why they failed
        ▼
  src/api/main.py (FastAPI)
        │  - GET  /health
        │  - GET  /schedule/sections, /schedule/trains, /schedule/trains/{id}
        │  - GET  /simulate/baseline
        │  - POST /simulate/disruption
        ▼
  dashboard/ (Vite + React)
        - dispatcher-console UI consuming the API above
```

## Module responsibilities

### `src/data/loader.py`
Loads the four raw dataset files (`stations.json`, `trains.json`,
`schedules.json`, `etrain_delays.csv`) into normalized pandas DataFrames.
Handles GeoJSON FeatureCollection parsing for stations (Point geometry) and
trains (LineString geometry), tolerating missing/null geometry.

### `src/network/graph_builder.py`
Builds two artifacts: a `NetworkX DiGraph` of the physical rail network
(nodes = stations with lat/long/zone, edges = direct station-to-station
links used by some train, weighted by distance and average travel time), and
`train_routes` (ordered stop sequences per train). Both are pickled to
`data/processed/`.

### `src/data/generate_synthetic_section.py`
Selects a contiguous, busy corridor from the network graph and packages it —
corridor station sequence, block sections (with line type, length, max
speed, headway), and the trains that traverse it (with their real stop times
and priority ranks) — into `data/synthetic/section_configs.json`, the input
format the optimizer expects.

### `src/optimizer/cp_sat_model.py`
The core scheduling solver. See [FORMULA.md](FORMULA.md) for the exact
constraint/objective formulation. Reads `section_configs.json`, writes
`optimized_schedule.json`.

### `src/simulator/schedule_simulator.py`
A `ScheduleSimulator` class that:
- Loads the section config and optimizer output
- `check_conflicts()`: independently re-derives capacity/headway conflicts
  from raw entry times (does not trust the optimizer's internal state)
- `inject_delay(train, section, minutes, propagate)`: mutates a train's
  entry time and (optionally) cascades the delay through its later
  sections, then re-checks for conflicts
- `reset()`: restores the clean baseline plan

This class is also the environment the RL modules build on.

### `src/rl/environment.py` (v1) and `environment_v2.py` (v2)
Both wrap `ScheduleSimulator` as a learnable environment. v1 is a
single-decision episode (effectively a contextual bandit — see
[APPROACH.md](APPROACH.md) for why it was superseded). v2 is a genuine
multi-step MDP with a conflict queue that supports cascading disruptions.
See [FORMULA.md](FORMULA.md) for the exact reward/state formulations of
each.

Both files also define baseline agents (`RandomAgent`,
`GreedyHoldLowerPriorityAgent` / `GreedyHoldOtherAgent`) used purely as
comparison points, not part of the learned system.

### `src/rl/train_qlearning.py` / `train_qlearning_v2.py`
Tabular Q-learning trainers matched to their respective environment
versions. v2 uses the real bootstrapped Q-learning update since v2 episodes
have genuine multi-step structure; v1 uses the simpler bandit-style update.
Both evaluate the trained policy against the random and greedy baselines on
a held-out seed and print the resulting Q-table for inspection.

### `src/rl/diagnose_gaveup.py`
A read-only diagnostic (does not train or modify the environment). Runs the
greedy agent over a fixed evaluation seed, and for every episode that hits
the step cap without resolving, records and classifies the conflict-queue
trajectory (BACKLOG / UNSTABLE CASCADE / TRANSIENT SPIKE — see
[FORMULA.md](FORMULA.md) for the exact classification rule).

### `src/api/`
FastAPI application exposing the simulator's capabilities over HTTP.

- `main.py` — app entrypoint, mounts routers, defines `/health`
- `models/schemas.py` — Pydantic request/response models (the API's public
  contract, versioned independently of route logic)
- `routes/schedule.py` — read-only endpoints over the optimizer's output
  (`/schedule/sections`, `/schedule/trains`, `/schedule/trains/{id}`)
- `routes/simulate.py` — `/simulate/baseline` (independent conflict
  verification) and `/simulate/disruption` (what-if delay injection)

Each request constructs a fresh `ScheduleSimulator` instance, so concurrent
requests never share mutated state.

### `dashboard/`
Vite + React frontend, styled as a dispatcher control console rather than a
generic admin dashboard: dark theme derived from railway signal colors
(green/amber/red for clear/caution/conflict states), monospace typography
for train numbers and times, and a literal horizontal "track timeline"
visualization as the signature UI element for viewing a section's train
sequence. In progress — talks to the FastAPI backend at
`http://127.0.0.1:8000`.

## Data flow: file formats at each boundary

| From → To | File | Key fields |
|---|---|---|
| loader → graph_builder | (in-memory DataFrames) | station_code, lat/long, train_number, arrival/departure, day |
| graph_builder → (pickle) | `data/processed/network_graph.gpickle`, `train_routes.pkl` | station adjacency, per-train ordered stops |
| generate_synthetic_section → optimizer | `data/synthetic/section_configs.json` | `corridor_stations`, `block_sections[]` (from/to, length_km, max_speed_kmph, line_type, headway_minutes), `trains[]` (train_number, priority_rank, stops_on_corridor) |
| optimizer → simulator/RL/API | `data/synthetic/optimized_schedule.json` | `train_schedules{train_number: [{section, section_index, scheduled_entry_min, recommended_entry_min, delay_min}]}`, `section_precedence` |

## Why this layering

Each stage writes a plain JSON/pickle artifact rather than passing objects
in-process, deliberately: it means every stage can be run, inspected, and
re-run independently (which is exactly how each module in this project was
validated — see [APPROACH.md](APPROACH.md)), and the simulator/RL/API layers
never need to re-derive anything the optimizer already computed; they only
ever read `optimized_schedule.json` as their source of truth for the
baseline plan.