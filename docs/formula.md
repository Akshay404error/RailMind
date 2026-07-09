# Formulas & Math Reference

This document is the precise math behind each module, so results can be
checked or reimplemented without reverse-engineering the code.

## 1. Section transit duration

For each block section `s`, with length in km and a max speed in km/h:

```
duration(s) = max(1, round(length_km(s) / max_speed_kmph(s) * 60))   [minutes]
```

Rounded to at least 1 minute to avoid a degenerate zero-duration section.

## 2. CP-SAT optimizer

### Decision variables

For every train `t` and every section `s` it traverses:

```
entry(t, s) ∈ [nominal_entry(t,s) − EARLY_BUFFER, nominal_entry(t,s) + LATE_BUFFER]
```

with `EARLY_BUFFER = 0` (a train cannot be dispatched earlier than
scheduled — that's not a real option) and `LATE_BUFFER = 180` minutes (a
train can be held, generously, up to 3 hours in this MVP).

### Continuity constraint

A train can't enter its next section before clearing the current one:

```
entry(t, s_next) ≥ entry(t, s) + duration(s)      for consecutive sections s, s_next
```

### Capacity / headway constraint

Per section, using OR-Tools' cumulative resource constraint: each train
occupies the section for `duration(s) + headway(s)` minutes starting at its
entry time, and the total simultaneous occupancy can never exceed the
section's capacity (1 for single-line, 2 for double-line):

```
Cumulative({ interval(t, s) : t traverses s }, demands = 1, capacity = section_capacity(s))
```

### Objective

Minimize total priority-weighted delay at each train's final corridor
section:

```
delay(t) = actual_exit(t) − nominal_exit(t)
         = (entry(t, last_section) + duration(last_section)) − nominal_exit(t)

minimize:  Σ_t  PRIORITY_WEIGHT(t) × delay(t)
```

Priority weights (mirrored everywhere priority matters in this project):

| Priority rank | Class | Weight |
|---|---|---|
| 1 | Premium | 3 |
| 2 | Express | 2 |
| 3 | Passenger | 1 |

Since `EARLY_BUFFER = 0`, `delay(t) ≥ 0` always, so no clamping to zero is
needed in the model.

### Optimality gap

```
gap = (objective − best_known_bound) / objective × 100%
```

`FEASIBLE` (not `OPTIMAL`) means the solver found a valid, constraint-
respecting solution within the time limit (30s), but has not proven it's the
mathematically best possible — the gap quantifies how far it might be from
optimal, not whether it's safe to use. A feasible solution is always
conflict-free; the gap only bears on efficiency, not safety.

## 3. Simulator: conflict detection

Independent of the optimizer's own bookkeeping. For a given section, sort
all trains' `(entry, exit)` intervals by entry time and sweep with a sliding
window: a train stays "active" in the window while
`window_member.exit + headway(s) > new_train.entry`. Whenever the active-set
size exceeds `section_capacity(s)`, that's a conflict.

## 4. RL v1 (single-step / contextual bandit)

### Reward

```
reward = −1.0 × (1 if unresolved else 0) − 0.01 × added_delay_minutes
```

where `added_delay_minutes = holding_time × PRIORITY_WEIGHT(held_train)`.

### Escalating hold

Repeatedly apply a hold of exactly one `headway(s)` period to the chosen
train, re-checking after each application, up to `MAX_HOLD_ITERATIONS = 20`
times, stopping as soon as the *specific* targeted conflict clears.

### Update rule (v1)

Because v1 episodes are single-decision (no real next-state), the correct
simplification of Q-learning is a **contextual bandit update**:

```
Q(s, a) ← Q(s, a) + α × (reward − Q(s, a))
```

with `α = 0.1` fixed.

## 5. RL v2 (multi-step / genuine MDP)

### Reward (per step)

```
reward = (0 if resolved else −1.0) − 0.01 × added_delay − STEP_COST
```

with `STEP_COST = 0.02`, added specifically so the agent doesn't take more
steps than necessary once a working resolution exists.

### Gave-up penalty

If the episode hits `MAX_STEPS_PER_EPISODE = 10` with conflicts still
queued, every remaining conflict is counted unresolved:

```
reward −= 1.0 × len(remaining_queue)
```

### Update rule (v2) — real Q-learning with bootstrapping

```
Q(s, a) ← Q(s, a) + α × (r + γ × max_a' Q(s', a') − Q(s, a))
```

with `α = 1 / N(s, a)` (visit-count-based learning rate, guarantees proper
convergence) and `γ = 0.9`.

### Epsilon schedule

Linear decay from `ε = 1.0` to `ε = 0.05` over the first 30,000 of 60,000
training episodes, held at 0.05 thereafter.

## 6. Q-learning state representation (v2)

```
state = (queue_length_bucket, delay_bucket, higher_priority_rank, lower_priority_rank)
```

- `queue_length_bucket ∈ {0, 1, 2, 3+}` — 0 means nothing pending (terminal)
- `delay_bucket ∈ {0, 1, 2}` — the *originating* disruption's delay severity:
  `0` if ≤10 min, `1` if 11–20 min, `2` if >20 min
- `higher_priority_rank`, `lower_priority_rank ∈ {1, 2, 3}` — the priority
  ranks of the two trains in the *current* conflict at the front of the
  queue (min/max of the pair, so the state is symmetric under which train
  happened to be "train_a" vs "train_b")

This is intentionally small (at most 4 × 3 × 3 × 3 = 108 states) so the
learned Q-table stays a fully inspectable lookup table.

## 7. Diagnostic classification (gave-up episodes)

Given the queue-length trace over an episode's real steps (excluding the
final forced-clear-to-zero, which is an artifact of giving up, not a real
resolution):

```
deltas[i] = trace[i+1] − trace[i]

if all(deltas ≤ 0):
    → BACKLOG (shrinking every step, just needed more steps)
elif last 3 deltas are all ≥ 0 and at least one > 0:
    → UNSTABLE CASCADE (still growing/flat right at the cutoff)
else:
    → TRANSIENT SPIKE (grew at some point, genuinely recovering by the end)
```