"""
RailMind - API Models

Pydantic request/response schemas. Kept separate from route logic so the
API's public contract is easy to review/version independent of how it's
implemented.
"""

from typing import Optional
from pydantic import BaseModel, Field


class SectionInfo(BaseModel):
    section_index: int
    from_station: str
    to_station: str
    line_type: str
    capacity: int
    headway_minutes: float
    duration_minutes: float


class TrainSectionEntry(BaseModel):
    section: str
    section_index: int
    scheduled_entry_min: float
    recommended_entry_min: float
    delay_min: float


class TrainScheduleResponse(BaseModel):
    train_number: str
    stops: list[TrainSectionEntry]


class ConflictInfo(BaseModel):
    section_index: int
    section_name: str
    train_a: str
    train_b: str
    reason: str
    detail: str


class BaselineConflictResponse(BaseModel):
    conflict_free: bool
    num_conflicts: int
    conflicts: list[ConflictInfo]


class DisruptionRequest(BaseModel):
    train_number: str = Field(..., description="Train number as it appears in the schedule, e.g. '12004'")
    section_index: int = Field(..., description="Index of the section this train is delayed entering")
    delay_min: float = Field(..., gt=0, description="Extra delay in minutes, must be positive")
    propagate: bool = Field(True, description="Whether to push back this train's later sections too")


class DisruptionResponse(BaseModel):
    train_number: str
    section_index: int
    delay_min: float
    new_conflicts: list[ConflictInfo]
    conflict_free: bool


class HealthResponse(BaseModel):
    status: str
    trains_loaded: int
    sections_loaded: int


# APPEND these to the bottom of your existing src/api/models/schemas.py
# (Optional is already imported there; add `from typing import Optional` if not.)

class ReportEmailRequest(BaseModel):
    to: list[str] = Field(..., min_length=1, description="Recipient email addresses")
    subject: Optional[str] = None
    train_number: Optional[str] = None
    section_index: Optional[int] = None
    delay_min: Optional[float] = Field(None, gt=0)


class ReportEmailResponse(BaseModel):
    sent: bool
    recipients: list[str]