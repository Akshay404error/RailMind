"""
RailMind - API Routes: Corridor

GET /schedule/corridor returns every block section with all its train
occupants in ONE call (instead of 1 request per train), with conflict flags
computed by the simulator (capacity + headway), not by a naive gap check.
"""

from fastapi import APIRouter

from src.api.priorities import load_priorities
from src.simulator.schedule_simulator import ScheduleSimulator

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("/corridor")
def corridor():
    sim = ScheduleSimulator()
    prio = load_priorities()
    conflicts = sim.check_conflicts()

    flagged = set()
    for c in conflicts:
        flagged.add((c.section_index, c.train_a))
        flagged.add((c.section_index, c.train_b))

    by_section = {i: [] for i in range(len(sim.sections))}
    for train, stops in sim.train_schedules.items():
        for stop in stops:
            idx = stop["section_index"]
            if idx not in by_section:
                continue
            by_section[idx].append({
                "train": train,
                "entry_min": stop["recommended_entry_min"],
                "delay_min": stop["delay_min"],
                "priority": prio.get(train),
                "conflict": (idx, train) in flagged,
            })

    sections = []
    for idx, s in enumerate(sim.sections):
        occ = sorted(by_section[idx], key=lambda o: o["entry_min"])
        sections.append({
            "section_index": idx,
            "name": f"{s['from_station']} -> {s['to_station']}",
            "line_type": s["line_type"],
            "capacity": sim.section_capacity[idx],
            "headway_minutes": sim.section_headway[idx],
            "duration_minutes": sim.section_durations[idx],
            "occupants": occ,
        })
    return {"conflict_count": len(conflicts), "sections": sections}