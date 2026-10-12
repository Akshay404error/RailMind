"""
RailMind - API Entrypoint

Run from the project root:  uvicorn src.api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from src.api.routes import schedule, simulate, report, corridor
from src.api.models.schemas import HealthResponse
from src.api.security import install
from src.simulator.schedule_simulator import ScheduleSimulator

app = FastAPI(
    title="RailMind API",
    description="Precedence/crossing schedule optimization, conflict verification, and disruption simulation.",
    version="0.3.0",
)

app.include_router(schedule.router)
app.include_router(simulate.router)
app.include_router(report.router)
app.include_router(corridor.router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health():
    """Confirms the API can load the underlying data files and reports basic counts."""
    sim = ScheduleSimulator()
    return HealthResponse(
        status="ok",
        trains_loaded=len(sim.entries),
        sections_loaded=len(sim.sections),
    )


# Must stay LAST. Adds login protection for every route (except /auth, /docs, /health),
# activity logging, CORS for the dashboard, and the /auth, /admin and /report/pdf routes.
# CORS is handled inside install(), so there is no separate CORSMiddleware block here.
install(app)