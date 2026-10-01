"""HTTP routes. Each handler validates input, calls a service, and returns."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from energyflow.api.dependencies import get_disaggregation_service
from energyflow.disaggregation import DisaggregatedReading, EnergyDisaggregationService
from energyflow.models import EnergyReading

router = APIRouter()

DisaggregationService = Annotated[
    EnergyDisaggregationService,
    Depends(get_disaggregation_service),
]


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
) -> DisaggregatedReading:
    return await service.disaggregate(reading)
