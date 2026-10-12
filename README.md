# RailMind

**AI-assisted precedence/crossing optimization for railway block sections.**

RailMind takes a real train-schedule dataset for a rail corridor, models it as a
graph of stations and block sections, and solves for a conflict-free
entry-time schedule using constraint programming (Google OR-Tools CP-SAT). A
reinforcement-learning layer then handles the harder problem: when a real
disruption knocks a train off its planned entry time, what's the least-costly
way to re-sequence around it in real time, without re-running the full
optimizer?

On top of that sits a dispatcher-style web console with secure email-OTP login,
live conflict checking, a what-if disruption simulator, PDF/email reports, and an
admin activity trail.

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
| REST API | Schedule, corridor, simulation, report and admin endpoints | ✅ Working |
| Dashboard | Dispatcher console: corridor timeline, priority colours, disruption simulator, reports | ✅ Working |
| Email-OTP login | Passwordless sign-in, new-user signup form, JWT sessions | 🧪 New, under test |
| PDF reports + email | Live report as PDF, optionally mailed | 🧪 New, under test |
| Audit trail + admin alerts | Per-user activity log with IP/location, login alert mails, daily activity PDF | 🧪 New, under test |

## Features

- **Corridor console** - all block sections, trains, priorities (Premium / Express / Passenger) and conflict flags from a single `GET /schedule/corridor` call, refreshed every 30 s.
- **Disruption simulator** - inject a delay on any train and see the real conflict list from the simulator.
- **Reports** - live report as HTML or PDF (`/report/pdf`), with an optional what-if scenario, and email delivery.
- **Email OTP login** - enter an email, receive a 6-digit code (5-minute expiry, 5 attempts, single use). First-time users complete a short details form. Sessions are signed JWTs.
- **Admin visibility** - every sign-in records IP address, approximate location and device and emails an alert to the admin. Simulations, reports and admin actions are logged per user. A PDF activity report is emailed daily and can be downloaded or sent on demand from the dashboard.

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
```

### Run the API and dashboard

```powershell
# one-time: configuration (never commit .env)
copy .env.example .env
# then edit .env: set JWT_SECRET, SMTP_* and ADMIN_EMAIL (see Configuration below)

# terminal 1 - backend
uvicorn src.api.main:app --reload
# API docs: http://127.0.0.1:8000/docs

# terminal 2 - dashboard
cd dashboard
npm install
npm run dev
# console: http://localhost:5173
```

For local testing without working email, set `DEV_PRINT_OTP=1` in `.env`; the
login code is then also printed in the backend terminal.

Full step-by-step instructions, including expected output at each stage, are
in [USE.md](docs/USE.md).

## Configuration

All settings live in `.env` (copy from `.env.example`). Never commit this file.

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Signs login sessions. Use a long random string: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Outgoing mail. For Gmail use `smtp.gmail.com`, port `587`, and an **app password** (needs 2-Step Verification) |
| `ADMIN_EMAIL` | Receives login alerts and activity PDFs; signing in with this address unlocks the admin panel |
| `ADMIN_EMAILS` | Optional extra admin addresses (comma separated) |
| `ACTIVITY_REPORT_HOUR` | Local hour (0-23) for the daily activity PDF, default `20` |
| `ALLOWED_EMAIL_DOMAIN` | Optional, e.g. `gmail.com`, to restrict who can sign up |
| `CORS_ORIGINS` | Dashboard origins allowed to call the API, default `http://localhost:5173,http://127.0.0.1:5173` |
| `TRUSTED_PROXY` | Set to `1` only behind nginx/Cloudflare so the real client IP is read from `X-Forwarded-For` |
| `DEV_PRINT_OTP` | Set to `1` in development to print login codes in the terminal |
| `AUTH_DB` | Optional path of the SQLite file for users and the activity log (default `data/auth.db`) |

Train priorities for colouring and reports are read from
`data/synthetic/train_priorities.json` in the form `{"12004": 1, "12816": 2}`
(1 = Premium, 2 = Express, 3 = Passenger). Trains not listed default to Passenger.

## API overview

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | public | Data loaded + counts |
| `POST /auth/request-otp` | public | Email a 6-digit login code |
| `POST /auth/verify-otp` | public | Verify the code; returns a session, or a signup token for new users |
| `POST /auth/register` | signup token | Create the account from the details form |
| `GET /auth/me`, `POST /auth/logout` | login | Current user / record sign-out |
| `GET /schedule/corridor` | login | All sections, trains, priorities, conflict flags |
| `GET /schedule/...` | login | Per-train schedules |
| `GET /simulate/baseline` | login | Re-verify the optimizer output |
| `POST /simulate/disruption` | login | What-if delay on one train |
| `GET /report/html`, `GET /report/pdf` | login | Live report (optional `train_number`, `section_index`, `delay_min`) |
| `POST /report/email` | login | Email the report |
| `GET /admin/activity`, `GET /admin/activity.pdf`, `POST /admin/activity/email` | admin | Activity log, PDF download, PDF email |

## Why this exists

Real corridors get re-planned from scratch far too rarely relative to how
often small disruptions happen. A CP-SAT solve is accurate but too slow to
re-run for every 5-minute delay. RailMind's RL layer is the fast, local
fallback: it doesn't replace the optimizer, it handles the gap between
optimizer runs.

## Validated results (135-train corridor, 7 block sections)

- CP-SAT solver: FEASIBLE solution, 240 weighted delay-minutes, 3.8–15.4%
  optimality gap depending on run (see [formula.md](docs/formula.md) for what
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

The login, PDF-report and activity-log features were added after this
validation and have not yet had the same independent verification.

## Security and privacy notes

- Secrets (`.env`, the SQLite file `data/auth.db`) are git-ignored; do not commit them. Use a Gmail **app password**, never your normal password.
- Login codes are stored only as keyed hashes, expire after 5 minutes, are single use, and are limited to 5 attempts.
- The activity log records each user's email, IP address, approximate location (looked up from the IP via ipwho.is) and device. Location is city-level at best. If you run RailMind for real users, tell them this is recorded.
- Every API route except `/health` and `/auth/*` requires a valid session token.

## Documentation

- [approach.md](docs/approach.md) — the problem-solving methodology used to build this: why CP-SAT + RL, and how each stage was validated before moving to the next
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — module breakdown, data flow, file structure
- [formula.md](docs/formula.md) — the actual math: objective functions, constraints, reward shaping, Q-learning update rule
- [WORKING.md](docs/WORKING.md) — how a request flows through the system end to end, plus the cascade-instability investigation
- [USE.md](docs/USE.md) — step-by-step run instructions for every module

## Project structure

```
railmind/
├── src/
│   ├── data/             # loader.py, generate_synthetic_section.py
│   ├── network/          # graph_builder.py
│   ├── optimizer/        # cp_sat_model.py
│   ├── simulator/        # schedule_simulator.py
│   ├── rl/               # environment.py, environment_v2.py, train_qlearning*.py, diagnose_*.py
│   └── api/
│       ├── main.py       # app entry point
│       ├── security.py   # login enforcement, activity logging, CORS, admin routes, daily PDF
│       ├── auth.py       # email-OTP login, signup, sessions
│       ├── audit.py      # activity log, IP geolocation, admin login alerts
│       ├── mailer.py     # shared SMTP sender
│       ├── activity_pdf.py   # activity report PDF
│       ├── priorities.py     # train priority lookup
│       ├── models/schemas.py
│       └── routes/       # schedule.py, simulate.py, corridor.py, report.py, report_pdf.py
├── dashboard/            # Vite + React dispatcher console
│   └── src/
│       ├── App.jsx, api.js, auth.js
│       └── components/   # Login, AccountBar, ActivityPanel, TopBar, Sidebar,
│                         # TrackTimeline, DisruptionPanel, ReportPanel
├── data/synthetic/       # section_configs.json, optimized_schedule.json, train_priorities.json
├── docs/                 # documentation set
├── tests/
├── .env.example          # configuration template (copy to .env)
└── requirements.txt
```

## Stack

Python 3.12, OR-Tools CP-SAT, pandas, NetworkX, FastAPI, SQLite, ReportLab,
PyJWT, Vite + React.

## Status

Core pipeline (data → graph → optimizer → simulator → RL) is built and
validated against real data. The API and dashboard are live. Login, PDF
reports and the activity trail are newly added and under test. See
[WORKING.md](docs/WORKING.md) for the honest state of known limitations.