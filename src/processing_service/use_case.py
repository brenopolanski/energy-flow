"""Process one accepted reading.

This module depends on the domain and the repository ports. It does not
import Celery, FastAPI, or the ingestion and results services.
"""

from pydantic import ValidationError

from energyflow_contracts.events import ReadingAccepted
from energyflow_contracts.readings import EnergyReading
from processing_service.domain import EnergyDisaggregationService
from processing_service.persistence.repository import EnergyReadingRepository
from processing_service.persistence.results import (
    DisaggregationResultRepository,
    StoredDisaggregation,
)


class PermanentProcessingError(Exception):
    """A failure that will not succeed on another attempt."""


class InvalidReadingError(PermanentProcessingError):
    """The event cannot be validated or disaggregated."""


async def process_accepted_reading(
    event: ReadingAccepted,
    *,
    readings: EnergyReadingRepository,
    results: DisaggregationResultRepository,
    service: EnergyDisaggregationService,
) -> StoredDisaggregation:
    """Validate, disaggregate, and store the split for ``event``.

    When a split is already stored for ``event.reading_id``, that row is
    returned and the service is not called again.
    """
    existing = await results.find_by_reading_id(event.reading_id)
    if existing is not None:
        return existing

    reading = _reading(event)
    try:
        disaggregated = await service.disaggregate(reading)
    except (ValidationError, ValueError) as exc:
        raise InvalidReadingError(f"reading {event.reading_id} is invalid") from exc
    await readings.save_with_id(event.reading_id, reading)
    return await results.save(event.reading_id, disaggregated)


def _reading(event: ReadingAccepted) -> EnergyReading:
    try:
        return EnergyReading.model_validate(
            {
                "sensor_id": event.sensor_id,
                "timestamp": event.timestamp,
                "power_watts": event.power_watts,
            }
        )
    except ValidationError as exc:
        raise InvalidReadingError(f"reading {event.reading_id} is invalid") from exc
