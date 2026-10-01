"""Process one stored reading.

This is the background use case. It depends on the domain service and the
repository ports. It does not import Celery, FastAPI, or a database driver.
"""

from uuid import UUID

from pydantic import ValidationError

from energyflow.disaggregation import EnergyDisaggregationService
from energyflow.models import EnergyReading
from energyflow.persistence.repository import EnergyReadingRepository, StoredEnergyReading
from energyflow.persistence.results import (
    DisaggregationResultRepository,
    StoredDisaggregation,
)


class PermanentProcessingError(Exception):
    """A failure that will not succeed on another attempt."""


class ReadingNotFoundError(PermanentProcessingError):
    """The reading id is not in storage."""


class InvalidStoredReadingError(PermanentProcessingError):
    """The stored row cannot be validated or disaggregated."""


class InvalidTaskArgumentError(PermanentProcessingError):
    """The task argument is not a reading id."""


async def process_stored_reading(
    reading_id: UUID,
    *,
    readings: EnergyReadingRepository,
    results: DisaggregationResultRepository,
    service: EnergyDisaggregationService,
) -> StoredDisaggregation:
    """Load, validate, disaggregate, and store the split for ``reading_id``.

    When a split is already stored, that row is returned and the service is
    not called again.
    """
    existing = await results.find_by_reading_id(reading_id)
    if existing is not None:
        return existing

    stored = await readings.find_by_id(reading_id)
    if stored is None:
        raise ReadingNotFoundError(f"reading {reading_id} was not found")

    reading = _validate_stored(stored)
    try:
        disaggregated = await service.disaggregate(reading)
    except (ValidationError, ValueError) as exc:
        raise InvalidStoredReadingError(
            f"stored reading {stored.id} is invalid"
        ) from exc
    return await results.save(stored.id, disaggregated)


def _validate_stored(stored: StoredEnergyReading) -> EnergyReading:
    try:
        return EnergyReading.model_validate(
            {
                "sensor_id": stored.sensor_id,
                "timestamp": stored.timestamp,
                "power_watts": stored.power_watts,
            }
        )
    except ValidationError as exc:
        raise InvalidStoredReadingError(
            f"stored reading {stored.id} is invalid"
        ) from exc
