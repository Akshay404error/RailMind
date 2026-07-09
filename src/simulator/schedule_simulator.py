"""
RailMind - Schedule Simulator

Replays an optimizer-produced schedule (data/synthetic/optimized_schedule.json)
against the section configuration (data/synthetic/section_configs.json) to:

  1. Independently verify the plan is conflict-free (capacity + headway),
     without trusting the CP-SAT model's own internal bookkeeping.
  2. Support "what-if" disruption testing: inject an extra delay on one
     train and see which downstream section occupancy constraints break,
     if any. This is the realistic operational use case - a plan gets
     validated once, then reality diverges (a train runs late) and you
     need to know fast whether the rest of the plan still holds.
  3. Serve as the environment the RL module (src/rl/) will step through:
     reset() / inject_delay() / get_state() give RL a consistent interface
     to a corridor's dynamics without re-implementing conflict-checking
     logic separately.

This is intentionally NOT a re-implementation of the optimizer. It trusts
recommended_entry_min values as ground truth UNLESS a disruption is
injected, in which case it recomputes downstream occupancy purely from
section capacity/headway rules (re-optimizing around a disruption is the
optimizer's job, not the simulator's).
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
CONFIG_PATH = SYNTHETIC_DIR / "section_configs.json"
SCHEDULE_PATH = SYNTHETIC_DIR / "optimized_schedule.json"


@dataclass
class ConflictEvent:
    section_index: int
    section_name: str
    train_a: str
    train_b: str
    reason: str
    detail: str


class ScheduleSimulator:
    def __init__(self, config_path=CONFIG_PATH, schedule_path=SCHEDULE_PATH):
        self.config = self._load_json(config_path)
        self.schedule = self._load_json(schedule_path)

        self.sections = self.config["block_sections"]
        self.section_durations = self._compute_durations(self.sections)
        self.section_capacity = [2 if s["line_type"] == "double" else 1 for s in self.sections]
        self.section_headway = [s["headway_minutes"] for s in self.sections]

        self.train_schedules = self.schedule["train_schedules"]
        self._base_entries = self._extract_entries(self.train_schedules)

        self.reset()

    @staticmethod
    def _load_json(path: Path):
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _compute_durations(sections):
        durations = []
        for s in sections:
            duration = max(1, round(s["length_km"] / s["max_speed_kmph"] * 60))
            durations.append(duration)
        return durations

    @staticmethod
    def _extract_entries(train_schedules):
        """train_number -> {section_index: recommended_entry_min}"""
        entries = {}
        for train_number, stops in train_schedules.items():
            entries[train_number] = {
                stop["section_index"]: stop["recommended_entry_min"] for stop in stops
            }
        return entries

    def reset(self):
        """Reset simulator state back to the optimizer's original recommended plan."""
        self.entries = {t: dict(sec_map) for t, sec_map in self._base_entries.items()}
        self.conflicts: list = []
        return self.get_state()

    def inject_delay(self, train_number: str, section_index: int, extra_delay_min: float,
                      propagate: bool = True) -> list:
        """
        Simulate a train running extra_delay_min later than recommended when
        entering section_index. If propagate=True, pushes back every later
        section entry for that same train (conservative: delay never
        recovers automatically - a real dispatcher would need to actively
        speed up or re-sequence to claw time back, which is a decision for
        the optimizer/RL layer, not assumed here).

        Returns any new conflicts this creates against OTHER trains' plans.
        """
        if train_number not in self.entries or section_index not in self.entries[train_number]:
            raise ValueError(f"No entry found for train {train_number} at section {section_index}")

        self.entries[train_number][section_index] += extra_delay_min

        if propagate:
            for idx in sorted(self.entries[train_number].keys()):
                if idx <= section_index:
                    continue
                prev_idx = idx - 1
                if prev_idx in self.entries[train_number]:
                    min_allowed = self.entries[train_number][prev_idx] + self.section_durations[prev_idx]
                    if self.entries[train_number][idx] < min_allowed:
                        self.entries[train_number][idx] = min_allowed

        return self.check_conflicts(section_indices=list(self.entries[train_number].keys()))

    def check_conflicts(self, section_indices: Optional[list] = None) -> list:
        """
        Recomputes occupancy per section and flags any capacity/headway
        violation using a sliding-window overlap check. Returns a list of
        ConflictEvent. Appends findings to self.conflicts as a side effect.
        """
        target_sections = section_indices if section_indices is not None else range(len(self.sections))
        found = []

        for idx in target_sections:
            occupants = []
            for train_number, sec_map in self.entries.items():
                if idx not in sec_map:
                    continue
                entry = sec_map[idx]
                exit_ = entry + self.section_durations[idx]
                occupants.append((train_number, entry, exit_))

            occupants.sort(key=lambda x: x[1])
            capacity = self.section_capacity[idx]
            headway = self.section_headway[idx]
            section_name = f"{self.sections[idx]['from_station']} -> {self.sections[idx]['to_station']}"

            active = []
            for train_number, entry, exit_ in occupants:
                active = [a for a in active if a[2] + headway > entry]
                active.append((train_number, entry, exit_))
                if len(active) > capacity:
                    conflicting = [a[0] for a in active]
                    found.append(ConflictEvent(
                        section_index=idx,
                        section_name=section_name,
                        train_a=conflicting[-2],
                        train_b=conflicting[-1],
                        reason="capacity_or_headway_violation",
                        detail=(
                            f"{len(active)} trains overlap in '{section_name}' "
                            f"(capacity={capacity}, headway={headway}min): "
                            f"{[(t, round(e, 1)) for t, e, _ in active]}"
                        ),
                    ))

        self.conflicts.extend(found)
        return found

    def get_state(self) -> dict:
        """
        Snapshot suitable as an RL observation base: per-train section entry
        map, and any accumulated conflicts.
        """
        return {
            "num_trains": len(self.entries),
            "num_sections": len(self.sections),
            "entries": {t: dict(m) for t, m in self.entries.items()},
            "conflicts": [c.__dict__ for c in self.conflicts],
        }

    def summary(self) -> str:
        lines = [
            f"Trains: {len(self.entries)}  Sections: {len(self.sections)}",
            f"Conflicts found: {len(self.conflicts)}",
        ]
        for c in self.conflicts[:20]:
            lines.append(f"  [{c.section_name}] {c.detail}")
        if len(self.conflicts) > 20:
            lines.append(f"  ... and {len(self.conflicts) - 20} more")
        return "\n".join(lines)


def main():
    print("Loading schedule + section config...")
    sim = ScheduleSimulator()

    print("Validating optimizer output is conflict-free (baseline check)...")
    baseline_conflicts = sim.check_conflicts()
    if not baseline_conflicts:
        print("  OK: baseline schedule has zero capacity/headway conflicts.")
    else:
        print(f"  WARNING: {len(baseline_conflicts)} conflicts found in baseline schedule!")
        print(sim.summary())

    print("\nDemo: injecting a 20-minute delay on the first train's first section...")
    first_train = next(iter(sim.entries))
    first_section = min(sim.entries[first_train].keys())
    new_conflicts = sim.inject_delay(first_train, first_section, extra_delay_min=20)

    print(f"Train {first_train} delayed 20 min at section {first_section}.")
    if new_conflicts:
        print(f"  This delay creates {len(new_conflicts)} new conflict(s):")
        for c in new_conflicts:
            print(f"    [{c.section_name}] {c.detail}")
    else:
        print("  No new conflicts - the schedule absorbs this delay safely.")

    print("\n" + sim.summary())


if __name__ == "__main__":
    main()