"""
RailMind - Cascade Bottleneck Locator

Follow-up to diagnose_pileups_v2.py's finding: every step in a gave-up
episode shows resolved=True for its own conflict, yet the queue still
grows in most of them - meaning each hold is very likely knocking its
train into a NEW conflict further down the corridor.

This script asks the natural next question: is that cascade spread evenly
across all sections, or is one specific section acting as a recurring
bottleneck? Tallies, for every step across all gave-up episodes, which
section was being handled and how many new conflicts it produced.
"""

from collections import Counter, defaultdict

from environment_v2 import RailCorridorEnv, GreedyHoldLowerPriorityAgent

EVAL_SEED = 999
NUM_EPISODES = 300


def trace_episode_with_sections(env: RailCorridorEnv, agent):
    obs = env.reset()
    if obs["queue_length"] == 0:
        return [], False

    steps = []
    done = False
    info = {}

    while not done:
        queue_before = len(env.episode_state["queue"])
        section = obs["current_section"]  # the section this step is about to act on

        action = agent.act(obs)
        obs, reward, done, info = env.step(action)

        queue_after = info["queue_length_after"]
        new_conflicts_added = max(0, queue_after - (queue_before - 1))

        steps.append({"section": section, "new_conflicts_added": new_conflicts_added})

    gave_up = bool(info.get("gave_up"))
    return steps, gave_up


def main():
    env = RailCorridorEnv(seed=EVAL_SEED)
    agent = GreedyHoldLowerPriorityAgent()

    section_step_counts = Counter()          # how often each section appears as "current"
    section_cascade_counts = Counter()       # how often that step produced >=1 new conflict
    section_total_new_conflicts = defaultdict(int)  # total new conflicts traced back to that section

    gave_up_total = 0

    for _ in range(NUM_EPISODES):
        steps, gave_up = trace_episode_with_sections(env, agent)
        if not gave_up:
            continue
        gave_up_total += 1
        for s in steps:
            sec = s["section"]
            section_step_counts[sec] += 1
            if s["new_conflicts_added"] > 0:
                section_cascade_counts[sec] += 1
            section_total_new_conflicts[sec] += s["new_conflicts_added"]

    print(f"Gave-up episodes analyzed: {gave_up_total}/{NUM_EPISODES}\n")

    if not section_step_counts:
        print("No gave-up episodes to analyze.")
        return

    print(f"{'section_index':>13} {'times_seen':>11} {'steps_that_cascaded':>20} "
          f"{'cascade_rate':>13} {'total_new_conflicts_traced_here':>32}")
    for sec in sorted(section_step_counts, key=lambda s: -section_total_new_conflicts[s]):
        seen = section_step_counts[sec]
        cascaded = section_cascade_counts[sec]
        rate = cascaded / seen if seen else 0.0
        total_new = section_total_new_conflicts[sec]
        print(f"{sec:>13} {seen:>11} {cascaded:>20} {rate:>12.1%} {total_new:>32}")

    print("\nIf one or two section_index values dominate 'total_new_conflicts_traced_here',")
    print("that's your bottleneck - the corridor's real constraint is concentrated there,")
    print("not spread evenly. If it's roughly even across all sections, the cascade is a")
    print("general property of the corridor's traffic density, not a single choke point.")


if __name__ == "__main__":
    main()