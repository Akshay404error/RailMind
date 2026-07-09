"""
RailMind - API Entrypoint

Run from the project root (C:\\railmind):

    uvicorn src.api.main:app --reload

Then open http://127.0.0.1:8000/docs for interactive Swagger docs -
FastAPI generates this automatically from the Pydantic models in
src/api/models/schemas.py, so it's always in sync with the real request/
response shapes, not a hand-maintained doc that can drift.
"""

from fastapi import FastAPI

from src.api.routes import schedule, simulate
from src.api.models.schemas import HealthResponse
from src.simulator.schedule_simulator import ScheduleSimulator

app = FastAPI(
    title="RailMind API",
    description="Precedence/crossing schedule optimization, conflict verification, and disruption simulation.",
    version="0.1.0",
)

app.include_router(schedule.router)
app.include_router(simulate.router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health():
    """Confirms the API can load the underlying data files and reports basic counts."""
    sim = ScheduleSimulator()
    return HealthResponse(
        status="ok",
        trains_loaded=len(sim.entries),
        sections_loaded=len(sim.sections),
    )