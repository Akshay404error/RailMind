"""
RailMind - Gave-Up Episode Diagnostic

Runs the greedy agent (deterministic, easiest to reason about) across the
same held-out eval seed used in train_qlearning_v2.py, and for every
episode that hits MAX_STEPS_PER_EPISODE without clearing the queue,
records the full step-by-step queue-length trace.

The question this answers: when an episode gives up, is it because...
  (A) BACKLOG - the queue started too large / shrinks too slowly to clear
      within the step cap, but is genuinely making progress each step
      (queue length is monotonically non-increasing), or
  (B) UNSTABLE CASCADE - resolving one conflict keeps generating new ones
      faster than they're cleared, so the queue length increases at some
      point during the episode and never really converges.

These are very different problems. (A) means "raise MAX_STEPS_PER_EPISODE"
is a reasonable fix. (B) means there's a structural issue - e.g. holding a
train at one section keeps knocking it into a conflict at the next
section, in a chain that doesn't actually terminate - and raising the
step cap alone won't fix it, it'll just delay when you notice.

This is intentionally observational - it doesn't change any agent or
environment logic. It only instruments and reports.
"""

from collections import Counter

from environment_v2 import RailCorridorEnv, GreedyHoldLowerPriorityAgent

EVAL_SEED = 999  # same held-out seed used in train_qlearning_v2.py's evaluate()
NUM_EPISODES = 300


def trace_episode(env: RailCorridorEnv, agent):
    """Runs one episode to completion, returning the full step trace."""
    obs = env.reset()
    trace = {
        "origin_train": obs["origin_train"],
        "origin_delay_min": obs["origin_delay_min"],
        "queue_lengths": [obs["queue_length"]],  # queue length BEFORE each step
        "resolved_flags": [],
        "gave_up": False,
    }

    # Some disruptions produce zero initial conflicts (e.g. the delayed
    # train has enough slack that nothing actually overlaps). That episode
    # is trivially done - no step() call needed, and environment_v2.step()
    # returns a differently-shaped info dict ({"note": ...}) if called on
    # an already-empty queue, which would otherwise KeyError below.
    if obs["queue_length"] == 0:
        trace["final_resolved_count"] = 0
        trace["final_unresolved_count"] = 0
        return trace

    done = False
    info = {}
    while not done:
        action = agent.act(obs)
        obs, reward, done, info = env.step(action)
        trace["queue_lengths"].append(info["queue_length_after"])
        trace["resolved_flags"].append(info["resolved_this_conflict"])

    trace["gave_up"] = bool(info.get("gave_up"))
    trace["final_resolved_count"] = info.get("resolved_count", 0)
    trace["final_unresolved_count"] = info.get("unresolved_count", 0)
    return trace


def classify_gave_up_trace(queue_lengths: list) -> str:
    """
    queue_lengths[i] -> queue length BEFORE step i, plus a final entry for
    after the last step. Classifies the failure mode from the shape of
    this sequence.

    IMPORTANT: when an episode gives up, the environment forcibly clears
    the queue to 0 on the final step (every remaining conflict is counted
    as unresolved, not actually cleared - see environment_v2.py's
    `gave_up` block). That forced drop-to-zero is NOT a real resolution
    and must be excluded from trend detection, or every gave-up episode
    looks like it was "recovering" right when it actually wasn't.
    """
    real_trajectory = queue_lengths[:-1]  # drop the artificial forced-clear-to-zero
    if len(real_trajectory) < 2:
        return "INSUFFICIENT DATA (gave up on step 1)"

    deltas = [real_trajectory[i + 1] - real_trajectory[i] for i in range(len(real_trajectory) - 1)]
    ever_grew = any(d > 0 for d in deltas)

    if not ever_grew:
        return "BACKLOG (queue shrank every real step, just ran out of steps)"

    tail = deltas[-3:] if len(deltas) >= 3 else deltas
    if all(d >= 0 for d in tail) and any(d > 0 for d in tail):
        return "UNSTABLE CASCADE (still growing/flat right up to the step cap)"
    return "TRANSIENT SPIKE (grew at some point, but was genuinely shrinking again by the end)"


def main():
    env = RailCorridorEnv(seed=EVAL_SEED)
    agent = GreedyHoldLowerPriorityAgent()

    all_traces = []
    for _ in range(NUM_EPISODES):
        all_traces.append(trace_episode(env, agent))

    gave_up = [t for t in all_traces if t["gave_up"]]
    not_gave_up = [t for t in all_traces if not t["gave_up"]]

    print(f"Total episodes: {len(all_traces)}")
    print(f"Gave up: {len(gave_up)}   Resolved cleanly: {len(not_gave_up)}")

    if not gave_up:
        print("\nNo gave-up episodes in this run - nothing to diagnose.")
        return

    avg_initial_queue_gaveup = sum(t["queue_lengths"][0] for t in gave_up) / len(gave_up)
    avg_initial_queue_ok = (
        sum(t["queue_lengths"][0] for t in not_gave_up) / len(not_gave_up) if not_gave_up else 0.0
    )
    print(f"\nAvg initial queue length - gave up: {avg_initial_queue_gaveup:.2f}  "
          f"vs resolved cleanly: {avg_initial_queue_ok:.2f}")

    classifications = Counter(classify_gave_up_trace(t["queue_lengths"]) for t in gave_up)
    print("\nFailure mode breakdown across gave-up episodes:")
    for label, count in classifications.most_common():
        print(f"  {count:>3}/{len(gave_up)}  {label}")

    print("\n--- Detailed traces (first 5 gave-up episodes) ---")
    for i, t in enumerate(gave_up[:5]):
        label = classify_gave_up_trace(t["queue_lengths"])
        print(f"\nEpisode gave-up #{i}: origin_train={t['origin_train']} "
              f"origin_delay={t['origin_delay_min']}min")
        print(f"  queue length before each step: {t['queue_lengths']}")
        print(f"  resolved this conflict, per step: {t['resolved_flags']}")
        print(f"  final: resolved={t['final_resolved_count']} unresolved={t['final_unresolved_count']}")
        print(f"  classification: {label}")


if __name__ == "__main__":
    main()