"""HTTP routes. Each handler validates input, calls a service, and returns."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from energyflow.api.dependencies import get_disaggregation_service, get_reading_publisher
from energyflow.disaggregation import DisaggregatedReading, EnergyDisaggregationService
from energyflow.messaging.publisher import ReadingEventPublisher
from energyflow.models import EnergyReading

router = APIRouter()

DisaggregationService = Annotated[
    EnergyDisaggregationService,
    Depends(get_disaggregation_service),
]
ReadingPublisher = Annotated[ReadingEventPublisher, Depends(get_reading_publisher)]


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/readings",
    response_model=DisaggregatedReading,
    status_code=status.HTTP_200_OK,
)
async def process_reading(
    reading: EnergyReading,
    service: DisaggregationService,
    publisher: ReadingPublisher,
) -> DisaggregatedReading:
    result = await service.disaggregate(reading)
    await publisher.publish_reading_accepted(reading)
    return result
