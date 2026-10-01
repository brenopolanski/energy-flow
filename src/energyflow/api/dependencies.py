"""How routes obtain the application service and the event publisher."""

from fastapi import Request

from energyflow.disaggregation import EnergyDisaggregationService
from energyflow.messaging.publisher import ReadingEventPublisher


def get_disaggregation_service() -> EnergyDisaggregationService:
    return EnergyDisaggregationService()


def get_reading_publisher(request: Request) -> ReadingEventPublisher:
    return request.app.state.publisher
