# Approach

This document describes *how* RailMind was built, not just what it does —
the reasoning behind each major decision and the validation discipline used
at every step. If you're extending this project, the process matters as much
as the code.

## The core problem, restated

Given a corridor (a sequence of stations connected by block sections, each
with a line type, capacity, and headway requirement) and a set of trains with
scheduled stop times and priority classes, produce entry times into each
block section for every train such that:

1. No section ever exceeds its capacity (1 train at a time for single-line,
   2 for double-line) within the required headway window.
2. A train can't enter its next section before it's physically left the
   previous one.
3. Total priority-weighted delay versus each train's original schedule is
   minimized.

That's the static problem. The harder problem, and the one most of the RL
work targets, is: **a train just ran late. What do you do about it right
now, without re-solving the whole corridor?**

## Why two different techniques (CP-SAT + RL), not one

CP-SAT (constraint programming) is the right tool for the static problem: it
finds a provably-near-optimal schedule and gives a hard guarantee that
capacity/headway constraints are respected. But it's not fast enough to
re-run every time a train is a few minutes late — real dispatch decisions
need to happen in seconds, not a 30-second solve.

Reinforcement learning is the right tool for the *reactive* problem: given a
disruption has already happened, learn a policy that decides "hold this
train or that one" fast, using a state representation small enough to be a
lookup table. It doesn't have to be globally optimal — it has to be better
than a human dispatcher's default instinct (the greedy baseline) and fast
enough to run in real time.

These aren't in competition. CP-SAT produces the baseline plan; RL handles
deviations from it between full re-solves.

## The validation discipline used throughout

Every module in this project was tested against **synthetic mock data before
being run on the real 135-train corridor**, and every claimed result was
independently re-checked rather than trusted from a single run. Concretely,
that meant:

- The simulator was built specifically so it does *not* just replay the
  optimizer's own internal bookkeeping — it recomputes conflicts from raw
  entry times using its own sliding-window overlap logic. A model can be
  wrong about its own correctness; an independent check can't inherit that
  mistake.
- Every RL environment change was tested against a hand-built mock corridor
  *before* running it on real data, specifically designed to trigger the
  failure mode being fixed (e.g. a 3-train pileup on a single-line section to
  test the escalating-hold fix).
- When a result looked good (e.g. a 15.4% optimality gap on one run, vs.
  3.8% on the previous run), the instinct was to explain *why* the numbers
  differ, not just report them — in that case, the CP-SAT solver's own
  internal search allocation between "finding a solution" and "proving
  optimality" varies run to run, even on identical input.
- When an RL agent converged to a trivial "always accept" policy on a first
  training run, that result was treated as a real finding to investigate
  (was it a bug, or a legitimate reward-tradeoff on that particular mock
  data?), not silently dismissed or re-run until it looked better.

## Iterative fix cycle: the RL environment's history

The RL environment went through two real, motivated redesigns rather than
one big design up front:

1. **v1 (single-decision episodes):** one disruption, one conflict, one
   action, episode ends. This is secretly a contextual bandit, not real
   Q-learning, because there's no next-state to bootstrap from.
2. **Discovered limitation:** validating v1 against real data showed that
   holding a train by a single fixed headway period often wasn't enough to
   clear multi-train pileups — the action "succeeded" at nothing.
3. **Fix:** made hold actions escalate internally (repeat the hold, checking
   after each attempt, up to a cap) rather than applying a single fixed
   nudge.
4. **Discovered limitation:** even with escalating holds, real disruptions
   sometimes produced *multiple simultaneous conflicts*, and v1 only ever
   looked at the first one, discarding the rest.
5. **v2 (multi-step episodes with a conflict queue):** a disruption seeds a
   queue of conflicts; the agent resolves them one at a time, and holding one
   train can surface *new* conflicts that get pushed back onto the same
   queue. This is a genuine multi-step MDP, so the Q-learning update was
   changed from a one-step contextual-bandit form to the real bootstrapped
   form: `Q(s,a) ← Q(s,a) + α(r + γ·max Q(s',a') − Q(s,a))`.
6. **Discovered limitation:** ~12% of disruptions, across *every* policy
   tested (random, greedy, and trained Q-learning), hit the step cap without
   resolving. Because this rate was policy-independent, it pointed at a
   structural issue with the corridor's slack, not a learning failure — a
   dedicated diagnostic script (`diagnose_gaveup.py`) was built specifically
   to distinguish "just needs more steps" (BACKLOG) from "genuinely unstable"
   (UNSTABLE CASCADE) by tracing the conflict-queue length step by step.

See [WORKING.md](WORKING.md) for the full detail on what that diagnostic
found, and [FORMULA.md](FORMULA.md) for the exact reward and update-rule math
at each stage.

## What "done" means for each module

Nothing in this project was marked complete on the strength of "the code ran
without an error." The bar used throughout was:

- Does it produce the same qualitative result on a hand-built mock where the
  correct answer is known in advance?
- Does the result on real data match domain intuition (e.g. do higher
  priority trains get held less often than lower-priority ones)?
- If a result is surprising, is there a concrete, checkable explanation for
  *why* — not just an assumption that it's fine?

## Honest scope boundary

This project optimizes a single corridor in isolation. It does not model
network-wide effects (a held train here affecting a *different* corridor
downstream), and the RL policy's state representation is intentionally small
and discrete for auditability — it is not a deep-learning approach, and that
was a deliberate choice given this is a safety-adjacent scheduling domain
where an inspectable Q-table beats an opaque neural policy.