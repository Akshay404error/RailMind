"""
RailMind - Tabular Q-Learning Trainer (v2, multi-step)

v1 episodes were single-decision, so Q-learning there was secretly a
contextual bandit (no real next-state, no bootstrapping needed). Now that
environment_v2 has genuine multi-step episodes - one action can change
what conflict comes next - this is a real MDP, so this trainer uses actual
Q-learning updates: Q(s,a) <- Q(s,a) + alpha * (r + gamma * max_a' Q(s',a') - Q(s,a))
with alpha = 1/N(s,a) for proper convergence (as validated in v1).

State representation:
    (queue_length_bucket, delay_bucket, higher_priority_rank, lower_priority_rank)
      queue_length_bucket: 0 (no conflicts pending), 1, 2, 3+
      delay_bucket:        0 (<=10min), 1 (11-20min), 2 (>20min) - the
                            ORIGINAL disruption's delay, constant for the
                            whole episode (a proxy for how severe the
                            triggering event was)
      higher/lower_priority_rank: 1-3, of the CURRENT conflict's pair
                            (0,0 placeholder when queue is empty)

state=(0,*,0,0) is effectively terminal (nothing left to resolve).
"""

import random
from collections import defaultdict

from environment_v2 import (
    RailCorridorEnv, RandomAgent, GreedyHoldLowerPriorityAgent,
    run_episodes, NUM_ACTIONS,
)

GAMMA = 0.9                       # future conflicts in the same pileup matter, but less than the immediate one
EPSILON_START = 1.0
EPSILON_END = 0.05
EPSILON_DECAY_EPISODES = 30000
NUM_TRAIN_EPISODES = 60000
NUM_EVAL_EPISODES = 300
EVAL_SEED = 999                   # held out, not used during training

ACTION_NAMES = {0: "ACCEPT", 1: "HOLD_HIGHER_PRIORITY", 2: "HOLD_LOWER_PRIORITY"}


def encode_state(obs: dict) -> tuple:
    if obs["num_conflicts"] == 0:
        return (0, 0, 0, 0)  # terminal / nothing pending

    queue_bucket = min(obs["queue_length"], 3)
    delay = obs["origin_delay_min"]
    delay_bucket = 0 if delay <= 10 else (1 if delay <= 20 else 2)
    higher = obs["higher_priority_train_rank"]
    lower = obs["lower_priority_train_rank"]
    return (queue_bucket, delay_bucket, higher, lower)


class QLearningAgent:
    def __init__(self, seed=None):
        self.q = defaultdict(lambda: [0.0] * NUM_ACTIONS)
        self.counts = defaultdict(lambda: [0] * NUM_ACTIONS)
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

    def update(self, state: tuple, action: int, reward: float, next_state: tuple, done: bool):
        self.counts[state][action] += 1
        alpha = 1.0 / self.counts[state][action]

        target = reward if done else reward + GAMMA * max(self.q[next_state])
        current = self.q[state][action]
        self.q[state][action] = current + alpha * (target - current)


def train():
    env = RailCorridorEnv(seed=1)
    agent = QLearningAgent(seed=1)

    episode_reward_history = []
    for ep in range(NUM_TRAIN_EPISODES):
        agent.epsilon = agent.epsilon_for(ep)

        obs = env.reset()
        state = encode_state(obs)
        done = False
        ep_reward = 0.0

        while not done:
            action = agent.act(state)
            next_obs, reward, done, _ = env.step(action)
            next_state = encode_state(next_obs)
            agent.update(state, action, reward, next_state, done)
            state = next_state
            ep_reward += reward

        episode_reward_history.append(ep_reward)

        if (ep + 1) % 5000 == 0:
            recent_avg = sum(episode_reward_history[-5000:]) / 5000
            print(f"  episode {ep + 1:>6}/{NUM_TRAIN_EPISODES} | epsilon={agent.epsilon:.3f} "
                  f"| avg episode reward (last 5000)={recent_avg:.3f}")

    return agent


def evaluate(agent: QLearningAgent, seed: int, num_episodes: int = NUM_EVAL_EPISODES):
    """Runs the learned policy greedily (epsilon=0) on a fresh, unseen episode sequence."""
    env = RailCorridorEnv(seed=seed)
    total_reward = 0.0
    total_steps = 0
    total_gave_up = 0
    action_counts = [0, 0, 0]

    for _ in range(num_episodes):
        obs = env.reset()
        state = encode_state(obs)
        done = False
        info = {}

        while not done:
            action = agent.act(state, greedy=True)
            action_counts[action] += 1
            next_obs, reward, done, info = env.step(action)
            state = encode_state(next_obs)
            total_reward += reward
            total_steps += 1

        if info.get("gave_up"):
            total_gave_up += 1

    avg = total_reward / num_episodes
    avg_steps = total_steps / num_episodes
    return avg, avg_steps, total_gave_up, action_counts


def print_learned_policy(agent: QLearningAgent):
    print("\nLearned policy (best action per visited state):")
    print(f"{'queue_len':>10} {'delay':>6} {'higher_pri':>11} {'lower_pri':>10}   best_action            "
          f"Q-values                    visits [accept,hold_hi,hold_lo]")
    low_confidence_states = []
    for queue_bucket in range(4):
        for delay_bucket in range(3):
            pri_range = (0,) if queue_bucket == 0 else (1, 2, 3)
            for higher in pri_range:
                for lower in (pri_range if queue_bucket else (0,)):
                    if queue_bucket > 0 and lower < higher:
                        continue  # lower-priority rank number must be >= higher's by definition
                    state = (queue_bucket, delay_bucket, higher, lower)
                    if state not in agent.q:
                        continue
                    qs = agent.q[state]
                    counts = agent.counts[state]
                    best = max(range(NUM_ACTIONS), key=lambda a: qs[a])
                    total_visits = sum(counts)
                    flag = "  <- LOW SAMPLE" if total_visits < 30 else ""
                    if flag:
                        low_confidence_states.append(state)
                    print(f"{queue_bucket:>10} {delay_bucket:>6} {higher:>11} {lower:>10}   "
                          f"{ACTION_NAMES[best]:<20}  {[round(v, 3) for v in qs]!s:<28} {counts}{flag}")

    if low_confidence_states:
        print(f"\n{len(low_confidence_states)} state(s) had fewer than 30 total samples - "
              f"treat their chosen action as unreliable, not as a real learned preference.")


def main():
    print("=== Training Q-learning agent (multi-step) ===")
    agent = train()

    print(f"\n=== Evaluating on held-out seed={EVAL_SEED} (unseen during training) ===")

    q_avg, q_steps, q_gave_up, q_actions = evaluate(agent, seed=EVAL_SEED)
    print(f"\nQ-learning agent: avg episode reward = {q_avg:.3f}  avg steps/episode={q_steps:.2f}  "
          f"gave up {q_gave_up}/{NUM_EVAL_EPISODES}")
    print(f"  actions taken: accept={q_actions[0]}, hold_higher={q_actions[1]}, hold_lower={q_actions[2]}")

    print("\nRandom baseline:")
    random_env = RailCorridorEnv(seed=EVAL_SEED)
    random_avg = run_episodes(random_env, RandomAgent(seed=EVAL_SEED),
                               num_episodes=NUM_EVAL_EPISODES, verbose=False)

    print("\nGreedy baseline:")
    greedy_env = RailCorridorEnv(seed=EVAL_SEED)
    greedy_avg = run_episodes(greedy_env, GreedyHoldLowerPriorityAgent(),
                               num_episodes=NUM_EVAL_EPISODES, verbose=False)

    print_learned_policy(agent)

    print("\n=== Summary ===")
    print(f"  Random:      {random_avg:.3f}")
    print(f"  Greedy:      {greedy_avg:.3f}")
    print(f"  Q-learning:  {q_avg:.3f}")

    if q_avg > greedy_avg:
        print(f"\nQ-learning BEAT the greedy heuristic ({q_avg:.3f} > {greedy_avg:.3f}).")
    elif q_avg == greedy_avg:
        print(f"\nQ-learning MATCHED the greedy heuristic ({q_avg:.3f}).")
    else:
        print(f"\nQ-learning did NOT beat the greedy heuristic ({q_avg:.3f} <= {greedy_avg:.3f}) "
              f"- check the printed policy above and the gave-up rate before assuming a broken reward.")


if __name__ == "__main__":
    main()