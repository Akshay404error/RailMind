"""
RailMind - RL Environment (v2, multi-step episodes)

v1 was a single-decision episode: one disruption, one conflict, one action.
This version extends that to a proper multi-step episode: a disruption can
produce SEVERAL conflicts at once (a genuine multi-train pileup), and
resolving one conflict (by holding a train) can itself surface NEW
conflicts elsewhere on the corridor (a real cascade, via propagate=True).
The agent now works through a QUEUE of conflicts, one decision per step,
until the queue empties (fully resolved) or a step cap is hit (gave up).

Action semantics changed from v1's DISRUPTED/OTHER framing to a
priority-based framing. In a multi-step episode there is no longer a
single fixed "disrupted train" throughout the whole episode - after the
first decision, later conflicts in the queue may not even involve the
train that started things off. Every conflict is just a pair of trains;
the meaningful, always-applicable choice is which one of the pair to hold:

Actions:
  0 = accept as-is (leave this specific conflict unresolved)
  1 = hold the HIGHER-priority train of the pair (expensive per minute,
      but sometimes genuinely cheaper if it resolves in fewer iterations
      - this is exactly the pattern the v1 richer-state experiment found)
  2 = hold the LOWER-priority train of the pair (the "obvious" choice -
      cheaper per minute, mirrors a human dispatcher's default instinct)

Each hold still escalates internally (one headway period at a time,
capped at MAX_HOLD_ITERATIONS) until that specific conflict clears - this
mechanism was already validated in v1 and is unchanged. What's new: any
additional conflicts surfaced by that hold get pushed onto the queue
instead of being silently discarded, and the episode keeps going -
multiple agent decisions per disruption, mirroring a real cascading
pileup - instead of stopping after a single action.

Reward per step:
  -1.0                       if this conflict is left unresolved
                             (action=accept, or hold escalation hit its
                             cap without clearing)
  -0.01 * added delay-minutes, priority-weighted
  -STEP_COST                 a small constant per step, so the agent
                             doesn't take more steps than necessary once
                             a resolution is already found

If the queue isn't empty by MAX_STEPS_PER_EPISODE, the episode ends and
every remaining conflict in the queue is counted as unresolved (same
-1.0 each) - a genuine "gave up" outcome, reported in info, not hidden.
"""

import random
from pathlib import Path
from typing import Optional
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `simulator` import
from simulator.schedule_simulator import ScheduleSimulator, ConflictEvent  # noqa: E402

PRIORITY_WEIGHT = {1: 3, 2: 2, 3: 1}  # Premium, Express, Passenger - mirrors cp_sat_model.py

ACTION_ACCEPT = 0
ACTION_HOLD_HIGHER_PRIORITY = 1
ACTION_HOLD_LOWER_PRIORITY = 2
NUM_ACTIONS = 3

MAX_STEPS_PER_EPISODE = 10
MAX_HOLD_ITERATIONS = 20
STEP_COST = 0.02


class RailCorridorEnv:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.sim = ScheduleSimulator()
        self._priority_lookup = self._build_priority_lookup()
        self.episode_state = None

    def _build_priority_lookup(self) -> dict:
        """train_number -> priority_rank (1/2/3), sourced from section_configs.json."""
        lookup = {}
        for train in self.sim.config.get("trains", []):
            lookup[train["train_number"]] = train.get("priority_rank", 2)
        return lookup

    def get_priority(self, train_number: str) -> int:
        """Public accessor for a train's priority rank (1=Premium ... 3=Passenger)."""
        return self._priority_lookup.get(train_number, 2)

    def reset(self):
        """
        Starts a new episode: reset simulator to the clean optimizer plan,
        inject one random disruption, and seed the conflict queue with
        whatever conflicts that disruption produces (possibly several, if
        it's a genuine pileup). Returns the initial observation.
        """
        self.sim.reset()

        candidates = [
            (t, idx) for t, sec_map in self.sim.entries.items() for idx in sec_map.keys()
        ]
        train_number, section_index = self.rng.choice(candidates)
        delay_min = self.rng.choice([5, 10, 15, 20, 25, 30])

        conflicts = self.sim.inject_delay(train_number, section_index, delay_min, propagate=True)

        self.episode_state = {
            "origin_train": train_number,
            "origin_section": section_index,
            "origin_delay_min": delay_min,
            "queue": list(conflicts),
            "step_count": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
        }
        return self._observe()

    def _observe(self) -> dict:
        st = self.episode_state
        queue = st["queue"]

        if not queue:
            return {
                "origin_train": st["origin_train"],
                "origin_delay_min": st["origin_delay_min"],
                "num_conflicts": 0,
                "queue_length": 0,
                "higher_priority_train_rank": None,
                "lower_priority_train_rank": None,
                "current_section": None,
            }

        current = queue[0]
        pri_a = self.get_priority(current.train_a)
        pri_b = self.get_priority(current.train_b)
        # lower rank number = higher real-world priority (1=Premium ... 3=Passenger)
        higher_rank = min(pri_a, pri_b)
        lower_rank = max(pri_a, pri_b)

        return {
            "origin_train": st["origin_train"],
            "origin_delay_min": st["origin_delay_min"],
            "num_conflicts": len(queue),
            "queue_length": len(queue),
            "higher_priority_train_rank": higher_rank,
            "lower_priority_train_rank": lower_rank,
            "current_section": current.section_index,
        }

    def _resolve_by_holding(self, train_to_hold: str, conflict: ConflictEvent,
                             max_iterations: int = MAX_HOLD_ITERATIONS):
        """
        Escalates a hold on train_to_hold at conflict.section_index by one
        headway period at a time until THIS SPECIFIC (section, train-pair)
        conflict clears, or max_iterations is hit. Mechanism unchanged from
        v1 (already validated there).

        Returns:
          resolved (bool)               - whether this exact conflict cleared
          other_new_conflicts (list)    - any DIFFERENT conflicts returned
                                           during escalation (i.e. not this
                                           same section+pair) - genuinely
                                           new, cascading conflicts to
                                           enqueue for a future step
          total_added_min (float)
          iterations_used (int)
        """
        headway = self.sim.section_headway[conflict.section_index]
        total_added = 0.0
        last_conflicts = []

        def is_same_conflict(c):
            return (c.section_index == conflict.section_index and
                    {c.train_a, c.train_b} == {conflict.train_a, conflict.train_b})

        for i in range(1, max_iterations + 1):
            last_conflicts = self.sim.inject_delay(
                train_to_hold, conflict.section_index, headway, propagate=True
            )
            total_added += headway
            still_same = any(is_same_conflict(c) for c in last_conflicts)
            if not still_same:
                other_new = [c for c in last_conflicts if not is_same_conflict(c)]
                return True, other_new, total_added, i

        other_new = [c for c in last_conflicts if not is_same_conflict(c)]
        return False, other_new, total_added, max_iterations

    def step(self, action: int):
        """
        Pops the current conflict off the queue, applies the action to it,
        and pushes any newly-surfaced cascading conflicts back onto the
        queue. Returns (observation, reward, done, info).
        """
        st = self.episode_state
        queue = st["queue"]

        if not queue:
            # Nothing pending. Shouldn't normally be stepped in this state,
            # but handle gracefully rather than crashing.
            return self._observe(), 0.0, True, {"note": "queue already empty"}

        current = queue.pop(0)
        pri_a = self.get_priority(current.train_a)
        pri_b = self.get_priority(current.train_b)

        if pri_a <= pri_b:  # lower number = higher real-world priority
            higher_train, lower_train = current.train_a, current.train_b
        else:
            higher_train, lower_train = current.train_b, current.train_a

        iterations = 0
        added_delay = 0.0
        resolved = False
        new_conflicts = []

        if action in (ACTION_HOLD_HIGHER_PRIORITY, ACTION_HOLD_LOWER_PRIORITY):
            train_to_hold = higher_train if action == ACTION_HOLD_HIGHER_PRIORITY else lower_train
            resolved, new_conflicts, added_min, iterations = self._resolve_by_holding(train_to_hold, current)
            weight = PRIORITY_WEIGHT.get(self.get_priority(train_to_hold), 2)
            added_delay = added_min * weight
        # ACTION_ACCEPT (or anything else): resolved stays False, no delay added

        if resolved:
            st["resolved_count"] += 1
        else:
            st["unresolved_count"] += 1

        # enqueue genuinely new cascading conflicts, deduped against what's already queued
        existing_keys = {(c.section_index, frozenset((c.train_a, c.train_b))) for c in queue}
        for c in new_conflicts:
            key = (c.section_index, frozenset((c.train_a, c.train_b)))
            if key not in existing_keys:
                queue.append(c)
                existing_keys.add(key)

        st["step_count"] += 1
        reward = (-1.0 if not resolved else 0.0) - 0.01 * added_delay - STEP_COST

        gave_up = st["step_count"] >= MAX_STEPS_PER_EPISODE and bool(queue)
        if gave_up:
            reward -= 1.0 * len(queue)  # every abandoned conflict counts as unresolved
            st["unresolved_count"] += len(queue)
            queue.clear()

        done = len(queue) == 0

        info = {
            "action_taken": action,
            "resolved_this_conflict": resolved,
            "added_delay_min": added_delay,
            "hold_iterations": iterations,
            "queue_length_after": len(queue),
            "gave_up": gave_up,
            "resolved_count": st["resolved_count"],
            "unresolved_count": st["unresolved_count"],
        }
        return self._observe(), reward, done, info


class RandomAgent:
    """Baseline: picks a uniformly random action every step. Sanity-check only."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def act(self, observation: dict) -> int:
        return self.rng.randint(0, NUM_ACTIONS - 1)


class GreedyHoldLowerPriorityAgent:
    """
    Heuristic baseline (not learned): always hold the lower-priority train
    of whichever conflict is current, else accept if nothing's pending.
    Mirrors a human dispatcher's default instinct, and is the bar an RL
    policy should beat.
    """

    def act(self, observation: dict) -> int:
        if observation["num_conflicts"] == 0:
            return ACTION_ACCEPT
        return ACTION_HOLD_LOWER_PRIORITY


def run_episodes(env: RailCorridorEnv, agent, num_episodes: int = 20, verbose: bool = True):
    total_reward = 0.0
    total_steps = 0
    total_gave_up = 0

    for ep in range(num_episodes):
        obs = env.reset()
        ep_reward = 0.0
        step_count = 0
        done = False
        info = {}

        while not done:
            action = agent.act(obs)
            obs, reward, done, info = env.step(action)
            ep_reward += reward
            step_count += 1

        total_reward += ep_reward
        total_steps += step_count
        if info.get("gave_up"):
            total_gave_up += 1

        if verbose:
            print(
                f"ep {ep:02d} | steps={step_count:>2} ep_reward={ep_reward:>7.2f} "
                f"resolved={info.get('resolved_count', 0)} unresolved={info.get('unresolved_count', 0)} "
                f"gave_up={info.get('gave_up', False)}"
            )

    avg_reward = total_reward / num_episodes
    avg_steps = total_steps / num_episodes
    print(f"\nAverage episode reward over {num_episodes} episodes: {avg_reward:.3f} "
          f"(avg steps/episode={avg_steps:.2f}, gave up {total_gave_up}/{num_episodes})")
    return avg_reward


def main():
    print("=== Baseline: Random agent ===")
    env = RailCorridorEnv(seed=42)
    run_episodes(env, RandomAgent(seed=42), num_episodes=20)

    print("\n=== Baseline: Greedy 'hold lower priority' heuristic agent ===")
    env2 = RailCorridorEnv(seed=42)  # same seed -> same disruption sequence, fair comparison
    run_episodes(env2, GreedyHoldLowerPriorityAgent(), num_episodes=20)


if __name__ == "__main__":
    main()