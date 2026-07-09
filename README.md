# RailMind

**AI-assisted precedence/crossing optimization for railway block sections.**

RailMind takes a real train-schedule dataset for a rail corridor, models it as a
graph of stations and block sections, and solves for a conflict-free
entry-time schedule using constraint programming (Google OR-Tools CP-SAT). A
reinforcement-learning layer then handles the harder problem: when a real
disruption knocks a train off its planned entry time, what's the least-costly
way to re-sequence around it in real time, without re-running the full
optimizer?

Repo: https://github.com/Akshay404error/RailMind

## What's actually in here

| Layer | What it does | Status |
|---|---|---|
| Data loader | Parses raw stations/trains/schedules/delays data | ✅ Working |
| Network graph | Builds the corridor as a directed graph (stations, block sections) | ✅ Working |
| CP-SAT optimizer | Solves precedence/crossing scheduling, minimizing priority-weighted delay | ✅ Working, validated |
| Simulator | Independently re-verifies the optimizer's output, supports "what-if" disruption injection | ✅ Working, validated |
| RL environment (v1 → v2) | Learns which train to hold when a disruption creates a conflict | ✅ Working, validated |
| Diagnostics | Traces exactly why some disruptions can't be resolved | ✅ Working |
| REST API | Exposes schedule, simulation, and disruption endpoints | ✅ Working |
| Dashboard | Dispatcher-style console UI for the corridor | 🚧 In progress |

## Quick start

```powershell
cd C:\railmind
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1. Load and inspect the raw data
python src/data/loader.py

# 2. Build the network graph
python src/network/graph_builder.py

# 3. Solve the corridor schedule
python src/optimizer/cp_sat_model.py

# 4. Verify it independently + try a disruption
python src/simulator/schedule_simulator.py

# 5. Train and evaluate the RL disruption-handling policy
python src/rl/train_qlearning_v2.py

# 6. Run the API
uvicorn src.api.main:app --reload
# then open http://127.0.0.1:8000/docs
```

Full step-by-step instructions, including expected output at each stage, are
in [USE.md](docs/USE.md).

## Why this exists

Real corridors get re-planned from scratch far too rarely relative to how
often small disruptions happen. A CP-SAT solve is accurate but too slow to
re-run for every 5-minute delay. RailMind's RL layer is the fast, local
fallback: it doesn't replace the optimizer, it handles the gap between
optimizer runs.

## Validated results (135-train corridor, 7 block sections)

- CP-SAT solver: FEASIBLE solution, 240 weighted delay-minutes, 3.8–15.4%
  optimality gap depending on run (see [FORMULA.md](docs/FORMULA.md) for what
  the gap means)
- Simulator: 0 conflicts on the baseline optimizer output (independently
  re-verified, not just trusting the solver's own bookkeeping)
- RL (Q-learning, multi-step): beats both random and greedy-heuristic
  baselines on held-out disruption scenarios
- Known limitation: ~12% of injected disruptions cascade into pileups that
  don't resolve within the step cap, regardless of which policy is used —
  this is a structural property of a tightly-packed schedule, not a policy
  quality problem. See [WORKING.md](docs/WORKING.md) for the full
  investigation.

## Documentation

- [APPROACH.md](docs/APPROACH.md) — the problem-solving methodology used to build this: why CP-SAT + RL, and how each stage was validated before moving to the next
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — module breakdown, data flow, file structure
- [FORMULA.md](docs/FORMULA.md) — the actual math: objective functions, constraints, reward shaping, Q-learning update rule
- [WORKING.md](docs/WORKING.md) — how a request flows through the system end to end, plus the cascade-instability investigation
- [USE.md](docs/USE.md) — step-by-step run instructions for every module

## Project structure

```
railmind/
├── src/
│   ├── data/            # loader.py, generate_synthetic_section.py
│   ├── network/          # graph_builder.py
│   ├── optimizer/         # cp_sat_model.py
│   ├── simulator/        # schedule_simulator.py
│   ├── rl/               # environment.py, environment_v2.py, train_qlearning.py,
│   │                       # train_qlearning_v2.py, diagnose_gaveup.py
│   └── api/               # main.py, models/schemas.py, routes/schedule.py, routes/simulate.py
├── dashboard/             # Vite + React dispatcher console (in progress)
├── data/synthetic/        # section_configs.json, optimized_schedule.json
├── docs/                  # this documentation set
└── requirements.txt
```

## Stack

Python 3.12, OR-Tools CP-SAT, pandas, NetworkX, FastAPI, Vite + React.

## Status

Core pipeline (data → graph → optimizer → simulator → RL) is built and
validated against real data. API is live. Dashboard is in progress. See
[WORKING.md](docs/WORKING.md) for the honest state of known limitations.