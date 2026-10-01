from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from energyflow.disaggregation import (
    DisaggregatedPower,
    DisaggregatedReading,
    EnergyDisaggregationService,
)
from energyflow.models import EnergyReading
from energyflow.persistence.repository import StoredEnergyReading
from energyflow.persistence.results import StoredDisaggregation
from energyflow.processing import (
    InvalidStoredReadingError,
    PermanentProcessingError,
    ReadingNotFoundError,
    process_stored_reading,
)

TIMESTAMP = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


class MemoryReadings:
    def __init__(self, stored: StoredEnergyReading | None) -> None:
        self.stored = stored

    async def find_by_id(self, reading_id: UUID) -> StoredEnergyReading | None:
        if self.stored is None or self.stored.id != reading_id:
            return None
        return self.stored


class MemoryResults:
    def __init__(self) -> None:
        self.rows: dict[UUID, StoredDisaggregation] = {}
        self.saves = 0

    async def find_by_reading_id(self, reading_id: UUID) -> StoredDisaggregation | None:
        return self.rows.get(reading_id)

    async def save(
        self,
        reading_id: UUID,
        result: DisaggregatedReading,
    ) -> StoredDisaggregation:
        self.saves += 1
        if reading_id in self.rows:
            return self.rows[reading_id]
        stored = StoredDisaggregation(
            reading_id=reading_id,
            sensor_id=result.sensor_id,
            timestamp=result.timestamp,
            breakdown=result.breakdown,
        )
        self.rows[reading_id] = stored
        return stored


class CountingService:
    def __init__(self) -> None:
        self.calls = 0
        self._service = EnergyDisaggregationService()

    async def disaggregate(self, reading: EnergyReading) -> DisaggregatedReading:
        self.calls += 1
        return await self._service.disaggregate(reading)


class TimeoutResults:
    async def find_by_reading_id(self, reading_id: UUID) -> StoredDisaggregation | None:
        raise TimeoutError("database timed out")


def _stored(power_watts: float) -> StoredEnergyReading:
    return StoredEnergyReading(
        id=uuid4(),
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=power_watts,
    )


@pytest.mark.parametrize(
    ("power_watts", "breakdown"),
    [
        (
            1600,
            DisaggregatedPower(
                total_power_watts=1600,
                refrigerator_watts=0,
                air_conditioner_watts=1500,
                water_heater_watts=0,
                other_watts=100,
            ),
        ),
        (
            6150,
            DisaggregatedPower(
                total_power_watts=6150,
                refrigerator_watts=150,
                air_conditioner_watts=1500,
                water_heater_watts=4500,
                other_watts=0,
            ),
        ),
    ],
)
async def test_process_loads_validates_disaggregates_and_stores(
    power_watts: float,
    breakdown: DisaggregatedPower,
) -> None:
    stored = _stored(power_watts)
    results = MemoryResults()
    service = CountingService()

    processed = await process_stored_reading(
        stored.id,
        readings=MemoryReadings(stored),
        results=results,
        service=service,
    )

    assert service.calls == 1
    assert results.saves == 1
    assert processed.reading_id == stored.id
    assert processed.sensor_id == "sensor-001"
    assert processed.timestamp == TIMESTAMP
    assert processed.breakdown == breakdown


async def test_process_is_idempotent_when_the_result_already_exists() -> None:
    stored = _stored(1600)
    results = MemoryResults()
    service = CountingService()

    first = await process_stored_reading(
        stored.id,
        readings=MemoryReadings(stored),
        results=results,
        service=service,
    )
    second = await process_stored_reading(
        stored.id,
        readings=MemoryReadings(stored),
        results=results,
        service=service,
    )

    assert second == first
    assert service.calls == 1
    assert results.saves == 1


async def test_process_raises_when_the_reading_is_missing() -> None:
    results = MemoryResults()
    service = CountingService()

    with pytest.raises(ReadingNotFoundError):
        await process_stored_reading(
            uuid4(),
            readings=MemoryReadings(None),
            results=results,
            service=service,
        )

    assert service.calls == 0
    assert results.saves == 0


async def test_process_rejects_a_stored_reading_that_fails_validation() -> None:
    stored = StoredEnergyReading.model_construct(
        id=uuid4(),
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=-5,
    )
    results = MemoryResults()
    service = CountingService()

    with pytest.raises(InvalidStoredReadingError):
        await process_stored_reading(
            stored.id,
            readings=MemoryReadings(stored),
            results=results,
            service=service,
        )

    assert service.calls == 0
    assert results.saves == 0
    assert issubclass(InvalidStoredReadingError, PermanentProcessingError)
    assert issubclass(ReadingNotFoundError, PermanentProcessingError)


async def test_database_timeout_propagates_from_the_repository() -> None:
    with pytest.raises(TimeoutError):
        await process_stored_reading(
            uuid4(),
            readings=MemoryReadings(None),
            results=TimeoutResults(),
            service=CountingService(),
        )
