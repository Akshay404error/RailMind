# Use

Step-by-step instructions to run every module, with the output you should
expect to see at each stage so you can confirm it worked before moving on.

## Setup

```powershell
cd C:\railmind
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

All commands below assume you're in the activated venv, in the project root
(`C:\railmind`), unless a step says otherwise.

## 1. Load and inspect the raw data

```powershell
python src/data/loader.py
```

Expected: a per-dataset summary (`[OK] stations: N rows, M columns`, etc.)
for `stations`, `trains`, `schedules`, `delays`, followed by a short preview
of each.

## 2. Build the network graph

```powershell
python src/network/graph_builder.py
```

Expected: node/edge counts for the built graph, a sample of edges, and a
data-quality summary (missing distances, missing travel times, isolated
stations, unusable single-stop trains). Saves
`data/processed/network_graph.gpickle` and `data/processed/train_routes.pkl`.

## 3. Generate a synthetic corridor section

```powershell
python src/data/generate_synthetic_section.py
```

Expected: confirmation of the selected corridor (station sequence, number of
block sections, number of trains). Saves
`data/synthetic/section_configs.json`.

## 4. Solve the corridor schedule

```powershell
python src/optimizer/cp_sat_model.py
```

Expected output looks like:

```
Solver status: FEASIBLE
Trains scheduled: 135
Wall time: ~30s
Objective value: ~240 (weighted delay-minutes)
Best known bound: ...
Optimality gap: ...%
Total positive delay across all trains/sections: ~715 min
```

`FEASIBLE` (not `OPTIMAL`) is expected and fine — it means a valid,
conflict-free schedule was found within the 30-second time limit, just not
proven mathematically optimal. See [FORMULA.md](FORMULA.md) for what the gap
actually measures. Saves `data/synthetic/optimized_schedule.json`.

## 5. Independently verify the plan + try a disruption

```powershell
python src/simulator/schedule_simulator.py
```

Expected: `OK: baseline schedule has zero capacity/headway conflicts`,
followed by a demo injecting a 20-minute delay on one train and reporting
whether it creates new conflicts.

## 6. Run the RL environment baselines

```powershell
python src/rl/environment_v2.py
```

Expected: random-agent and greedy-agent baseline results over 20 episodes
each, showing average reward, average steps per episode, and how many
episodes "gave up" (hit the step cap without resolving).

## 7. Train and evaluate the Q-learning policy

```powershell
python src/rl/train_qlearning_v2.py
```

This trains for 60,000 episodes (a few minutes) and prints progress every
5,000 episodes. Expected final output: a comparison of random / greedy /
Q-learning average reward on a held-out seed, plus the full learned policy
table (state → best action, with visit counts and a low-sample warning for
any state with fewer than 30 visits).

## 8. Diagnose unresolved disruptions

```powershell
python src/rl/diagnose_gaveup.py
```

Expected: a breakdown of how many evaluation episodes gave up, and a
classification of each (BACKLOG / UNSTABLE CASCADE / TRANSIENT SPIKE — see
[FORMULA.md](FORMULA.md)), with detailed step-by-step traces for the first
few gave-up episodes.

## 9. Run the API

Install FastAPI/uvicorn once, if you haven't:

```powershell
pip install fastapi uvicorn
```

Then, **from the project root** (not `src/rl` or any subfolder — this
matters, since `uvicorn src.api.main:app` needs to find a `src` package
relative to your current directory):

```powershell
cd C:\railmind
uvicorn src.api.main:app --reload
```

Expected: `Uvicorn running on http://127.0.0.1:8000`. Open
**http://127.0.0.1:8000/docs** in a browser for the interactive Swagger UI
covering:

- `GET /health`
- `GET /schedule/sections`
- `GET /schedule/trains`
- `GET /schedule/trains/{train_number}`
- `GET /simulate/baseline`
- `POST /simulate/disruption`

Visiting `http://127.0.0.1:8000/` directly will 404 — there's no route
defined at the root, only under `/docs` and the endpoints above.

## 10. Run the dashboard

```powershell
cd dashboard
npm install
npm run dev
```

Expected: a Vite dev server, typically at `http://localhost:5173`. The
dashboard talks to the API at `http://127.0.0.1:8000`, so **step 9 must
already be running** in a separate terminal before you load the dashboard.

If you see CORS errors in the browser console, confirm
`CORSMiddleware` is enabled in `src/api/main.py` allowing the dashboard's
origin (`http://localhost:5173`).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` on `uvicorn` | Running the command from inside a subfolder like `src/rl` | `cd` to the project root (`C:\railmind`) first |
| `ERROR: Error loading ASGI app. Could not import module "src.api.main"` | A file was saved under its downloaded filename instead of the expected one (e.g. `api_main.py` instead of `main.py`) | Rename the file to match exactly what's imported — check `src/api/main.py`, `src/api/models/schemas.py`, `src/api/routes/schedule.py`, `src/api/routes/simulate.py` |
| `{"detail":"Not Found"}` in the browser | Visited `/` instead of `/docs` or a real endpoint | Go to `http://127.0.0.1:8000/docs` |
| Dashboard can't reach the API | API isn't running, or CORS isn't configured | Confirm step 9 is running in a separate terminal; check CORS config |