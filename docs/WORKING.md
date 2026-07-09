# How It Works

_To be filled in once the CP-SAT model is implemented._

## Optimization model (planned)
- Decision variables: train order/precedence at each block section, platform assignment
- Hard constraints: safety headway, single-line crossing rules, platform capacity, train schedules
- Objective: minimize weighted total delay (weights by train priority: Rajdhani/Express > Passenger > Freight)
- Re-optimization: triggered on disruption events (breakdown, weather, delay) using a rolling horizon

## Simulation (planned)
- SimPy models trains moving through the network over simulated time
- Random disruption injection tests optimizer responsiveness
- Used for what-if scenario analysis (alternative routings, holding strategies)
