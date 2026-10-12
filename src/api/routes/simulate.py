"""
RailMind - API Routes: Simulate

  GET  /simulate/baseline    -> re-verifies the optimizer output is conflict-free
  POST /simulate/disruption  -> injects a delay on one train and reports new conflicts
"""

from fastapi import APIRouter, HTTPException

from src.api.models.schemas import (
    BaselineConflictResponse,
    ConflictInfo,
    DisruptionRequest,
    DisruptionResponse,
)
from src.simulator.schedule_simulator import ScheduleSimulator

router = APIRouter(prefix="/simulate", tags=["simulate"])


def _to_infos(conflicts) -> list[ConflictInfo]:
    return [ConflictInfo(**c.__dict__) for c in conflicts]


@router.get("/baseline", response_model=BaselineConflictResponse)
def simulate_baseline():
    """Independently re-checks the optimized schedule for capacity/headway conflicts."""
    sim = ScheduleSimulator()  # fresh instance per request, no shared state
    conflicts = sim.check_conflicts()
    return BaselineConflictResponse(
        conflict_free=len(conflicts) == 0,
        num_conflicts=len(conflicts),
        conflicts=_to_infos(conflicts),
    )


@router.post("/disruption", response_model=DisruptionResponse)
def simulate_disruption(req: DisruptionRequest):
    """What-if: delay one train at one section and return any conflicts it creates."""
    sim = ScheduleSimulator()
    try:
        new_conflicts = sim.inject_delay(
            req.train_number, req.section_index, req.delay_min, propagate=req.propagate
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return DisruptionResponse(
        train_number=req.train_number,
        section_index=req.section_index,
        delay_min=req.delay_min,
        new_conflicts=_to_infos(new_conflicts),
        conflict_free=len(new_conflicts) == 0,
    )