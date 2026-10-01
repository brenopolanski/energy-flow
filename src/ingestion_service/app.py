"""HTTP application for the ingestion service."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, status
from pydantic import AwareDatetime, BaseModel

from energyflow_contracts.events import ReadingAccepted
from energyflow_contracts.readings import EnergyReading, SensorId
from ingestion_service.publishing import (
    CeleryReadingAcceptedPublisher,
    ReadingAcceptedPublisher,
)

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


class AcceptedReading(BaseModel):
    """A reading that was validated and published."""

    id: UUID
    sensor_id: SensorId
    timestamp: AwareDatetime
    power_watts: float
    status: Literal["accepted"] = "accepted"


def get_publisher() -> ReadingAcceptedPublisher:
    raise RuntimeError("publisher dependency was not overridden")


Publisher = Annotated[ReadingAcceptedPublisher, Depends(get_publisher)]


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
    publisher: Publisher,
) -> AcceptedReading:
    event = ReadingAccepted.from_reading(uuid4(), reading)
    await publisher.publish(event)
    return AcceptedReading(
        id=event.reading_id,
        sensor_id=event.sensor_id,
        timestamp=event.timestamp,
        power_watts=event.power_watts,
    )


def create_app(publisher: ReadingAcceptedPublisher | None = None) -> FastAPI:
    app = FastAPI(title="EnergyFlow Ingestion", version="0.1.0")
    app.include_router(router)
    selected = publisher or CeleryReadingAcceptedPublisher()
    app.dependency_overrides[get_publisher] = lambda: selected
    return app


app = create_app()
