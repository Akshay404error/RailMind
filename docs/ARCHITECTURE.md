# Architecture

_To be filled in as the system is built._

## Components
- **Data layer** — raw datasets → cleaning → processed data → synthetic section configs
- **Network model** — graph of stations and block sections (NetworkX)
- **Optimizer** — OR-Tools CP-SAT model for precedence/crossing decisions
- **Simulator** — SimPy discrete-event simulation with disruption injection
- **API** — FastAPI serving schedules, simulations, KPIs
- **Dashboard** — React frontend for controllers

## Data flow
raw datasets -> loader -> cleaned data -> network graph + synthetic section params
-> optimizer -> schedule/recommendation -> API -> dashboard
                                        -> simulator (what-if scenarios)
