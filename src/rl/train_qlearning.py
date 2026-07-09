"""
RailMind - Tabular Q-Learning Trainer

Trains a small tabular Q-learning agent against RailCorridorEnv, trying to
beat the GreedyHoldOtherAgent heuristic baseline (avg reward -0.147 on the
real 135-train corridor, per the last validated environment run).

State representation (discretized - raw train_number/section_index values
wouldn't generalize as tabular keys, since most specific trains/sections
would only be seen a handful of times each):

    (num_conflicts_bucket, delay_bucket, priority_rank)
      num_conflicts_bucket: 0, 1, 2, 3+     (capped at 3)
      delay_bucket:         0 (<=10min), 1 (11-20min), 2 (>20min)
      priority_rank:        1 (Premium), 2 (Express), 3 (Passenger)

That's a 4 x 3 x 3 = 36-state table - small enough to fully explore, and
generalizes across whichever specific trains/sections a disruption hits.

Each episode is a single decision (see environment.py docstring) - there
is no next state within an episode, so this reduces to contextual-bandit-
style learning (Q-update has no bootstrapped next-state term).
"""

import random
from collections import defaultdict

from environment import (
    RailCorridorEnv, RandomAgent, GreedyHoldOtherAgent,
    run_episodes, NUM_ACTIONS,
)

ALPHA = 0.1                       # kept for reference; QLearningAgent now uses 1/N internally
EPSILON_START = 1.0
EPSILON_END = 0.05
EPSILON_DECAY_EPISODES = 30000
NUM_TRAIN_EPISODES = 60000
NUM_EVAL_EPISODES = 300
EVAL_SEED = 999                   # held out, not used during training

ACTION_NAMES = {0: "ACCEPT", 1: "HOLD_DISRUPTED", 2: "HOLD_OTHER"}


def encode_state(obs: dict, priority_rank: int) -> tuple:
    conflicts_bucket = min(obs["num_conflicts"], 3)
    delay = obs["injected_delay_min"]
    delay_bucket = 0 if delay <= 10 else (1 if delay <= 20 else 2)
    # 0 = no conflict (irrelevant), otherwise the other train's real priority (1-3).
    # This matters because added delay cost is weighted by whichever train is
    # held - without it, states mix "other train is cheap to hold" and
    # "other train is expensive to hold" cases together, washing out the signal.
    other_priority = obs["other_train_priority"] or 0
    return (conflicts_bucket, delay_bucket, priority_rank, other_priority)


class QLearningAgent:
    def __init__(self, seed=None):
        self.q = defaultdict(lambda: [0.0] * NUM_ACTIONS)
        self.counts = defaultdict(lambda: [0] * NUM_ACTIONS)  # visits per (state, action)
        self.rng = random.Random(seed)
        self.epsilon = EPSILON_START

    @staticmethod
    def epsilon_for(episode_idx: int) -> float:
        frac = min(1.0, episode_idx / EPSILON_DECAY_EPISODES)
        return EPSILON_START + frac * (EPSILON_END - EPSILON_START)

    def act(self, state: tuple, greedy: bool = False) -> int:
        if not greedy and self.rng.random() < self.epsilon:
            return self.rng.randint(0, NUM_ACTIONS - 1)
        qs = self.q[state]
        max_q = max(qs)
        best_actions = [a for a, v in enumerate(qs) if v == max_q]
        return self.rng.choice(best_actions)

    def update(self, state: tuple, action: int, reward: float):
        # Proper incremental sample-mean step size (1/N) instead of a fixed
        # alpha. A fixed alpha never lets an estimate settle - it keeps
        # reacting to the most recent noisy sample forever, which is
        # especially damaging for rarely-visited states (few samples ->
        # each one swings the estimate a lot). 1/N converges to the true
        # average as visits accumulate, while still adapting quickly early on.
        self.counts[state][action] += 1
        n = self.counts[state][action]
        alpha = 1.0 / n
        current = self.q[state][action]
        self.q[state][action] = current + alpha * (reward - current)


def train():
    env = RailCorridorEnv(seed=1)
    agent = QLearningAgent(seed=1)

    reward_history = []
    for ep in range(NUM_TRAIN_EPISODES):
        agent.epsilon = agent.epsilon_for(ep)

        obs = env.reset()
        priority = env.get_priority(obs["disrupted_train"])
        state = encode_state(obs, priority)

        action = agent.act(state)
        _, reward, _, _ = env.step(action)
        agent.update(state, action, reward)
        reward_history.append(reward)

        if (ep + 1) % 1000 == 0:
            recent_avg = sum(reward_history[-1000:]) / 1000
            print(f"  episode {ep + 1:>5}/{NUM_TRAIN_EPISODES} | epsilon={agent.epsilon:.3f} "
                  f"| avg reward (last 1000)={recent_avg:.3f}")

    return agent


def evaluate(agent: QLearningAgent, seed: int, num_episodes: int = NUM_EVAL_EPISODES):
    """Runs the learned policy greedily (epsilon=0) on a fresh, unseen episode sequence."""
    env = RailCorridorEnv(seed=seed)
    total_reward = 0.0
    action_counts = [0, 0, 0]

    for _ in range(num_episodes):
        obs = env.reset()
        priority = env.get_priority(obs["disrupted_train"])
        state = encode_state(obs, priority)
        action = agent.act(state, greedy=True)
        action_counts[action] += 1
        _, reward, _, _ = env.step(action)
        total_reward += reward

    return total_reward / num_episodes, action_counts


def print_learned_policy(agent: QLearningAgent):
    print("\nLearned policy (best action per visited state):")
    print(f"{'conflicts':>10} {'delay':>6} {'disrupted_pri':>13} {'other_pri':>10}   best_action      "
          f"Q-values                    visits [accept,hold_d,hold_o]")
    low_confidence_states = []
    for conflicts_bucket in range(4):
        for delay_bucket in range(3):
            for priority in (1, 2, 3):
                other_range = (0,) if conflicts_bucket == 0 else (1, 2, 3)
                for other_priority in other_range:
                    state = (conflicts_bucket, delay_bucket, priority, other_priority)
                    if state not in agent.q:
                        continue  # never visited during training - don't fabricate a policy for it
                    qs = agent.q[state]
                    counts = agent.counts[state]
                    best = max(range(NUM_ACTIONS), key=lambda a: qs[a])
                    total_visits = sum(counts)
                    flag = "  <- LOW SAMPLE" if total_visits < 30 else ""
                    if flag:
                        low_confidence_states.append(state)
                    print(f"{conflicts_bucket:>10} {delay_bucket:>6} {priority:>13} {other_priority:>10}   "
                          f"{ACTION_NAMES[best]:<15}  {[round(v, 3) for v in qs]!s:<28} {counts}{flag}")

    if low_confidence_states:
        print(f"\n{len(low_confidence_states)} state(s) had fewer than 30 total samples - "
              f"treat their chosen action as unreliable, not as a real learned preference.")


def main():
    print("=== Training Q-learning agent ===")
    agent = train()

    print(f"\n=== Evaluating on held-out seed={EVAL_SEED} (unseen during training) ===")

    q_avg, q_actions = evaluate(agent, seed=EVAL_SEED)
    print(f"\nQ-learning agent: avg reward = {q_avg:.3f}  "
          f"(actions: accept={q_actions[0]}, hold_disrupted={q_actions[1]}, hold_other={q_actions[2]})")

    print("\nRandom baseline:")
    random_env = RailCorridorEnv(seed=EVAL_SEED)
    random_avg = run_episodes(random_env, RandomAgent(seed=EVAL_SEED),
                               num_episodes=NUM_EVAL_EPISODES, verbose=False)

    print("\nGreedy baseline:")
    greedy_env = RailCorridorEnv(seed=EVAL_SEED)
    greedy_avg = run_episodes(greedy_env, GreedyHoldOtherAgent(),
                               num_episodes=NUM_EVAL_EPISODES, verbose=False)

    print_learned_policy(agent)

    print("\n=== Summary ===")
    print(f"  Random:      {random_avg:.3f}")
    print(f"  Greedy:      {greedy_avg:.3f}")
    print(f"  Q-learning:  {q_avg:.3f}")

    if q_avg > greedy_avg:
        print(f"\nQ-learning BEAT the greedy heuristic ({q_avg:.3f} > {greedy_avg:.3f}).")
    elif q_avg == greedy_avg:
        print(f"\nQ-learning MATCHED the greedy heuristic ({q_avg:.3f}) - no improvement, "
              f"but check the printed policy above to see if it's genuinely equivalent behavior.")
    else:
        print(f"\nQ-learning did NOT beat the greedy heuristic ({q_avg:.3f} <= {greedy_avg:.3f}) "
              f"- inspect the printed policy above: if it's picking ACCEPT in conflict states, "
              f"the reward tradeoff (delay cost vs conflict cost) needs revisiting, not the algorithm.")


if __name__ == "__main__":
    main()