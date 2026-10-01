"""HTTP routes. Each handler validates input, calls a port, and returns."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import AwareDatetime, BaseModel

from energyflow.api.dependencies import get_job_dispatcher, get_reading_repository
from energyflow.jobs import ReadingJobDispatcher
from energyflow.models import EnergyReading, SensorId
from energyflow.persistence.repository import EnergyReadingRepository

router = APIRouter()

Readings = Annotated[EnergyReadingRepository, Depends(get_reading_repository)]
Jobs = Annotated[ReadingJobDispatcher, Depends(get_job_dispatcher)]


class HealthResponse(BaseModel):
    status: str


class AcceptedReading(BaseModel):
    """A reading that was stored and queued for background processing."""

    id: UUID
    sensor_id: SensorId
    timestamp: AwareDatetime
    power_watts: float
    status: Literal["accepted"] = "accepted"


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/readings",
    response_model=AcceptedReading,
    status_code=status.HTTP_202_ACCEPTED,
)
async def accept_reading(
    reading: EnergyReading,
    readings: Readings,
    jobs: Jobs,
) -> AcceptedReading:
    stored = await readings.save(reading)
    await jobs.dispatch(stored.id)
    return AcceptedReading(
        id=stored.id,
        sensor_id=stored.sensor_id,
        timestamp=stored.timestamp,
        power_watts=stored.power_watts,
    )
