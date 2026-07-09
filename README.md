# RailMind — Intelligent Railway Traffic Optimization Using Hybrid AI

Decision-support system that helps section controllers optimize train precedence
and crossings using operations research (OR-Tools CP-SAT) and simulation (SimPy).

## Structure
- `data/` — raw datasets, processed data, synthetic section configs
- `src/data/` — data loading, cleaning, synthetic section generation
- `src/network/` — station/route graph model
- `src/optimizer/` — CP-SAT precedence/crossing optimization model
- `src/simulator/` — discrete-event simulation + disruption injection
- `src/rl/` — (phase 2) reinforcement learning agent
- `src/api/` — FastAPI backend
- `dashboard/` — React controller dashboard
- `docs/` — ARCHITECTURE.md, WORKING.md, USE.md

## Quick start
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Place downloaded datasets into `data/raw/` before running notebooks/scripts.

See `docs/USE.md` for full setup and usage instructions.
