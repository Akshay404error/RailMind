"""
RailMind - RL Environment (v1, MVP)

Wraps ScheduleSimulator as a conflict-resolution learning environment.

Problem framing (deliberately scoped down for a first working version):
  A random disruption is injected (one train runs late entering one
  section). This may or may not cascade into downstream capacity/headway
  conflicts. The agent observes a small feature vector describing the
  resulting conflict(s) and picks ONE corrective action. The environment
  applies that action, rechecks conflicts, and returns a reward.

  This is a single-decision episode (not a full multi-step time simulation)
  on purpose: it's the smallest version of the real problem ("a disruption
  just happened, what do you do about it") that still (a) uses the real
  simulator/optimizer data, and (b) has a well-defined state/action/reward
  loop an RL algorithm can learn from. Extending to multi-step, multi-train
  sequential decisions is the natural next iteration once this loop is
  validated end to end.

Actions:
  0 = accept as-is (no further intervention)
  1 = hold the DISRUPTED train, escalating by one headway period at a time
      (up to a capped number of attempts) until the conflict at that
      section actually clears - not just a single fixed nudge, since one
      headway often isn't enough when 3+ trains pile into a section
  2 = hold the OTHER conflicting train instead, same escalating approach
      (protects the disrupted/higher-priority train's slot)

Reward:
  -1.0 * (remaining conflicts after action)          [safety, dominant term]
  -0.01 * (total added delay-minutes, priority-weighted)  [efficiency, tie-break]

This keeps the model honest: an action that "resolves" a conflict by
creating a worse one, or by adding huge delay, is still penalized.
"""

import random
from pathlib import Path
from typing import Optional
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))  # allow `simulator` import
from simulator.schedule_simulator import ScheduleSimulator, ConflictEvent  # noqa: E402

PRIORITY_WEIGHT = {1: 3, 2: 2, 3: 1}  # Premium, Express, Passenger - mirrors cp_sat_model.py

ACTION_ACCEPT = 0
ACTION_HOLD_DISRUPTED = 1
ACTION_HOLD_OTHER = 2
NUM_ACTIONS = 3


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
        """
        Public accessor for a train's priority rank (1=Premium, 2=Express,
        3=Passenger). Needed outside the environment - e.g. by the
        Q-learning trainer, to build its state representation without
        reaching into a private attribute.
        """
        return self._priority_lookup.get(train_number, 2)

    def reset(self):
        """
        Starts a new episode: reset simulator to the clean optimizer plan,
        then inject one random disruption (train, section, delay minutes).
        Returns the initial observation.
        """
        self.sim.reset()

        candidates = [
            (t, idx) for t, sec_map in self.sim.entries.items() for idx in sec_map.keys()
        ]
        train_number, section_index = self.rng.choice(candidates)
        delay_min = self.rng.choice([5, 10, 15, 20, 25, 30])

        conflicts = self.sim.inject_delay(train_number, section_index, delay_min)

        self.episode_state = {
            "train_number": train_number,
            "section_index": section_index,
            "delay_min": delay_min,
            "conflicts": conflicts,
        }
        return self._observe()

    def _observe(self) -> dict:
        conflicts = self.episode_state["conflicts"]

        # priority of the OTHER conflicting train (not the disrupted one) -
        # this is what actually determines whether HOLD_DISRUPTED or
        # HOLD_OTHER is cheaper, since added delay is weighted by whichever
        # train's priority is being held. None if there's no conflict.
        other_train_priority = None
        if conflicts:
            disrupted = self.episode_state["train_number"]
            c = conflicts[0]
            other_train = c.train_b if c.train_a == disrupted else c.train_a
            other_train_priority = self.get_priority(other_train)

        return {
            "disrupted_train": self.episode_state["train_number"],
            "disrupted_section": self.episode_state["section_index"],
            "injected_delay_min": self.episode_state["delay_min"],
            "num_conflicts": len(conflicts),
            "conflict_sections": [c.section_index for c in conflicts],
            "other_train_priority": other_train_priority,
        }

    def _resolve_by_holding(self, train_to_hold: str, conflict: ConflictEvent,
                             max_iterations: int = 20):
        """
        Repeatedly holds train_to_hold by one more headway period at
        conflict.section_index, rechecking after each hold, until the
        conflict AT THAT SECTION clears or max_iterations is hit.

        A single fixed nudge often isn't enough when 3+ trains pile into
        one section (a real pattern seen on the actual 135-train corridor,
        not just an edge case) - this escalates the hold instead of giving
        up after one attempt. max_iterations caps runaway holding (an
        unresolvable pileup should be reported, not hidden behind an
        unrealistic multi-hour hold).

        Returns (final_conflicts_for_this_train, total_added_delay_min, iterations_used).
        """
        headway = self.sim.section_headway[conflict.section_index]
        total_added = 0.0
        new_conflicts = [conflict]

        for i in range(1, max_iterations + 1):
            new_conflicts = self.sim.inject_delay(
                train_to_hold, conflict.section_index, headway, propagate=True
            )
            total_added += headway
            still_conflicting_here = any(
                c.section_index == conflict.section_index for c in new_conflicts
            )
            if not still_conflicting_here:
                return new_conflicts, total_added, i

        return new_conflicts, total_added, max_iterations

    def step(self, action: int):
        """
        Applies a corrective action to the FIRST conflict of the episode
        (MVP: handles one conflict group per step; multiple independent
        conflict groups in one episode are future work). HOLD actions now
        escalate (see _resolve_by_holding) rather than applying one fixed
        nudge, so 3+ train pileups get a real chance at resolution.
        Returns (observation, reward, done, info).
        """
        conflicts = self.episode_state["conflicts"]
        done = True  # single-decision episode

        if not conflicts:
            # Nothing to resolve - only a sensible action is "accept"
            reward = 0.0 if action == ACTION_ACCEPT else -0.5
            return self._observe(), reward, done, {"note": "no conflicts existed"}

        conflict = conflicts[0]
        disrupted_train = self.episode_state["train_number"]
        iterations = 0

        if action == ACTION_HOLD_DISRUPTED:
            new_conflicts, added_min, iterations = self._resolve_by_holding(disrupted_train, conflict)
            added_delay = added_min * PRIORITY_WEIGHT.get(
                self._priority_lookup.get(disrupted_train, 2), 2
            )
        elif action == ACTION_HOLD_OTHER:
            other_train = conflict.train_b if conflict.train_a == disrupted_train else conflict.train_a
            new_conflicts, added_min, iterations = self._resolve_by_holding(other_train, conflict)
            added_delay = added_min * PRIORITY_WEIGHT.get(
                self._priority_lookup.get(other_train, 2), 2
            )
        else:  # ACTION_ACCEPT
            new_conflicts = conflicts  # unresolved
            added_delay = 0.0

        remaining = len(new_conflicts)
        reward = -1.0 * remaining - 0.01 * added_delay

        info = {
            "action_taken": action,
            "remaining_conflicts": remaining,
            "added_delay_min": added_delay,
            "hold_iterations": iterations,
        }
        return self._observe(), reward, done, info


class RandomAgent:
    """Baseline: picks a uniformly random action. Sanity-check only."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def act(self, observation: dict) -> int:
        return self.rng.randint(0, NUM_ACTIONS - 1)


class GreedyHoldOtherAgent:
    """
    Heuristic baseline (not learned): always hold the non-priority train
    if a conflict exists, else accept. This mirrors what a human dispatcher
    would likely do by default, and is the bar an RL policy should beat.
    """

    def act(self, observation: dict) -> int:
        if observation["num_conflicts"] == 0:
            return ACTION_ACCEPT
        return ACTION_HOLD_OTHER


def run_episodes(env: RailCorridorEnv, agent, num_episodes: int = 20, verbose: bool = True):
    total_reward = 0.0
    for ep in range(num_episodes):
        obs = env.reset()
        action = agent.act(obs)
        obs2, reward, done, info = env.step(action)
        total_reward += reward
        if verbose:
            print(
                f"ep {ep:02d} | train={obs['disrupted_train']:>6} "
                f"section={obs['disrupted_section']} delay={obs['injected_delay_min']:>3}min "
                f"initial_conflicts={obs['num_conflicts']} | action={action} "
                f"-> remaining={info.get('remaining_conflicts', 'n/a')} reward={reward:.2f}"
            )
    avg_reward = total_reward / num_episodes
    print(f"\nAverage reward over {num_episodes} episodes: {avg_reward:.3f}")
    return avg_reward


def main():
    print("=== Baseline: Random agent ===")
    env = RailCorridorEnv(seed=42)
    run_episodes(env, RandomAgent(seed=42), num_episodes=20)

    print("\n=== Baseline: Greedy 'hold other train' heuristic agent ===")
    env2 = RailCorridorEnv(seed=42)  # same seed -> same disruption sequence, fair comparison
    run_episodes(env2, GreedyHoldOtherAgent(), num_episodes=20)


if __name__ == "__main__":
    main()