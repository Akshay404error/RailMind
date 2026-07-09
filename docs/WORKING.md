# Working

This document walks through how a request actually moves through the
system, using real numbers from the validated 135-train, 7-section corridor,
and documents the cascade-instability investigation in full — including the
parts that didn't have a clean fix, because that's the honest state of the
project.

## End-to-end walkthrough: from raw data to a disruption decision

1. **Load.** `loader.py` reads the raw GeoJSON/CSV files and produces
   DataFrames for stations, trains, schedules, and delays.
2. **Build the network.** `graph_builder.py` turns the schedule data into a
   directed graph of stations connected by block sections actually used by
   some train, with distances and average travel times computed per edge.
3. **Pick a corridor.** `generate_synthetic_section.py` selects a busy,
   contiguous stretch of that graph — in the validated run, a 7-section
   corridor (ANVR → ANVT → CNJ → SBB → GZB → MIU → DER → BRKY) carrying 135
   distinct trains, mostly double-line with headways of 3–15 minutes.
4. **Solve.** `cp_sat_model.py` finds recommended entry times into every
   section for every train. On the validated run: `FEASIBLE`, objective 240
   weighted delay-minutes, optimality gap between 3.8% and 15.4% across
   different runs (the gap varies run-to-run because the solver splits its
   30-second budget between finding a good solution and proving optimality
   — see [FORMULA.md](FORMULA.md)), total positive delay 714–716 minutes
   across all trains.
5. **Verify independently.** `schedule_simulator.py` re-checks the plan from
   scratch using its own overlap logic (not the solver's internal state):
   confirmed 0 conflicts on the baseline plan.
6. **Simulate a disruption.** Injecting a real delay (e.g. 20 minutes on one
   train) and re-checking showed the simulator correctly finds *new*
   downstream conflicts the delay creates — this was the first real proof
   the simulator does more than just echo the optimizer.
7. **Learn a disruption-response policy.** The RL environment wraps the
   simulator: for a given disruption, the agent decides whether to hold the
   disrupted train, hold the conflicting train, or accept the conflict. On
   the validated run, the trained Q-learning policy beat both a random
   agent and a greedy "always hold the lower-priority train" heuristic.
8. **Serve it.** The FastAPI layer exposes the same simulator capabilities
   over HTTP, so a dispatcher-facing tool (the dashboard, or any other
   client) can query section status, a train's schedule, or run a what-if
   disruption check without touching Python directly.

## The cascade-instability investigation

This is worth documenting in detail because it's a real, only-partially-
resolved finding, not a clean success story.

### What was observed

Across every policy tested — random, greedy, and trained Q-learning — almost
exactly the same fraction of disruptions (roughly 12%, ~37/300 in the final
evaluation run) hit the step cap without ever fully resolving. Because this
rate didn't depend on which policy was used, that ruled out "the policy just
isn't smart enough" as the explanation — it pointed at something structural
in the corridor itself.

### The diagnostic built to investigate it

`diagnose_gaveup.py` runs the greedy agent over the same held-out evaluation
seed and, for every episode that gives up, records the conflict-queue length
before every single step, then classifies the shape of that trace (see
[FORMULA.md](FORMULA.md) for the exact rule). On the real corridor:

- **~60% (22/37) classified as TRANSIENT SPIKE** — the queue grew at some
  point but was trending back down by the end. Some of these (e.g. one
  traced episode: `6 → 5 → 5 → 6 → 6 → 6 → 5 → 4 → 3 → 2`) look like they'd
  genuinely resolve given a few more steps; the step cap of 10 was simply
  too tight for them.
- **~40% (15/37) classified as UNSTABLE CASCADE** — the queue was still flat
  or growing right up to the cutoff, with no sign of converging on its own.

### Why this matters and what it means practically

A key supporting finding: in every traced episode, **every single hold
action successfully resolved the specific conflict it targeted** (100% local
success rate). The problem isn't that holds fail — it's that resolving one
conflict, on a corridor with very little slack left after CP-SAT already
optimized it, reliably pushes the held train straight into a *new* conflict
at its next section. That's amplification, not failure.

This has a real operational implication: a small but non-trivial fraction of
severe disruptions on this corridor genuinely need either (a) a longer
decision horizon than a locally-reactive policy can provide, or (b) a full
CP-SAT re-solve, or (c) human dispatcher judgment — not because the RL
policy is bad, but because the corridor's schedule is tight enough that
local patches run out of room. This was surfaced and accepted as a known
limitation rather than papered over; see the "Known limitation" note in
[README.md](../README.md).

### What was explicitly not done

At the point this was last investigated, three options were on the table
and none had been implemented yet:

1. Fix the diagnostic classifier's edge cases further and re-run on the full
   evaluation set (the classifier itself had one bug found and fixed
   mid-investigation — it was initially fooled by the artificial
   forced-clear-to-zero that happens when an episode gives up, and mislabeled
   monotonically-growing traces as "recovering").
2. Add a re-sequencing action (swap two trains' order) instead of only
   holding, which might resolve UNSTABLE CASCADE cases without adding delay.
3. Accept the ~12% rate as a hand-off point to human dispatchers or a full
   optimizer re-solve, and move on to other parts of the system (this is the
   path that was actually taken, in favor of building out the API layer).

If you pick this back up, option 2 (re-sequencing) is the most promising
unexplored lead, since the root cause is specifically that *holding* has no
slack left to exploit, not that priority decisions are wrong.

## Known limitations, stated plainly

- The RL policy's state space is small and discrete by design (see
  [APPROACH.md](APPROACH.md)) — it will not distinguish between disruptions
  that a richer state representation could tell apart.
- The ~12% cascade-gave-up rate is a real, currently-unresolved limitation,
  not a rare edge case to be dismissed.
- The dashboard is in progress; the API and backend pipeline are the
  validated, complete parts of this project as of this writing.
- CORS must be enabled on the FastAPI backend for the dashboard (running on
  a different port) to reach it — confirm `CORSMiddleware` is configured in
  `src/api/main.py` before wiring up the frontend.