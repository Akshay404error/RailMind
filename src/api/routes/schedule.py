"""
RailMind - API Routes: Schedule

Read-only endpoints over the optimizer's output (data/synthetic/optimized_schedule.json)
and the section configuration it was solved against.
"""

from fastapi import APIRouter, HTTPException

from src.api.models.schemas import SectionInfo, TrainScheduleResponse, TrainSectionEntry
from src.simulator.schedule_simulator import ScheduleSimulator

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _get_simulator() -> ScheduleSimulator:
    # New instance per request: the simulator is cheap to construct (just
    # loads two JSON files) and this keeps requests fully independent -
    # no shared mutable state between concurrent API calls, which matters
    # because inject_delay() mutates self.entries in place.
    return ScheduleSimulator()


@router.get("/sections", response_model=list[SectionInfo])
def list_sections():
    """Returns the corridor's block sections with capacity/headway/duration."""
    sim = _get_simulator()
    sections = []
    for idx, s in enumerate(sim.sections):
        sections.append(SectionInfo(
            section_index=idx,
            from_station=s["from_station"],
            to_station=s["to_station"],
            line_type=s["line_type"],
            capacity=sim.section_capacity[idx],
            headway_minutes=sim.section_headway[idx],
            duration_minutes=sim.section_durations[idx],
        ))
    return sections


@router.get("/trains", response_model=list[str])
def list_trains():
    """Returns all train numbers present in the optimized schedule."""
    sim = _get_simulator()
    return sorted(sim.entries.keys())


@router.get("/trains/{train_number}", response_model=TrainScheduleResponse)
def get_train_schedule(train_number: str):
    """Returns the recommended per-section schedule for one train."""
    sim = _get_simulator()
    if train_number not in sim.train_schedules:
        raise HTTPException(status_code=404, detail=f"Train '{train_number}' not found in schedule")

    stops = [TrainSectionEntry(**stop) for stop in sim.train_schedules[train_number]]
    return TrainScheduleResponse(train_number=train_number, stops=stops)