from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from energyflow_contracts.events import ReadingAccepted
from energyflow_contracts.readings import EnergyReading
from processing_service.domain import (
    DisaggregatedPower,
    DisaggregatedReading,
    EnergyDisaggregationService,
)
from processing_service.persistence.repository import StoredEnergyReading
from processing_service.persistence.results import StoredDisaggregation
from processing_service.use_case import InvalidReadingError, process_accepted_reading

TIMESTAMP = datetime(2026, 9, 30, 22, 25, tzinfo=timezone.utc)


class MemoryReadings:
    def __init__(self) -> None:
        self.saved: list[StoredEnergyReading] = []

    async def save_with_id(self, reading_id: UUID, reading: EnergyReading) -> StoredEnergyReading:
        stored = StoredEnergyReading(
            id=reading_id,
            sensor_id=reading.sensor_id,
            timestamp=reading.timestamp,
            power_watts=reading.power_watts,
        )
        self.saved.append(stored)
        return stored


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


def _event(power_watts: float) -> ReadingAccepted:
    return ReadingAccepted.from_reading(
        uuid4(),
        EnergyReading(
            sensor_id="sensor-001",
            timestamp=TIMESTAMP,
            power_watts=power_watts,
        ),
    )


@pytest.mark.parametrize(
    ("power_watts", "air_conditioner_watts", "other_watts"),
    [(1600, 1500, 100), (6150, 1500, 0)],
)
async def test_process_validates_disaggregates_and_stores(
    power_watts: float,
    air_conditioner_watts: float,
    other_watts: float,
) -> None:
    event = _event(power_watts)
    readings = MemoryReadings()
    results = MemoryResults()
    service = CountingService()

    processed = await process_accepted_reading(
        event,
        readings=readings,
        results=results,
        service=service,
    )

    assert service.calls == 1
    assert results.saves == 1
    assert readings.saved[0].id == event.reading_id
    assert processed.reading_id == event.reading_id
    assert processed.breakdown.air_conditioner_watts == air_conditioner_watts
    assert processed.breakdown.other_watts == other_watts
    if power_watts == 6150:
        assert processed.breakdown == DisaggregatedPower(
            total_power_watts=6150,
            refrigerator_watts=150,
            air_conditioner_watts=1500,
            water_heater_watts=4500,
            other_watts=0,
        )


async def test_process_is_idempotent_when_the_result_already_exists() -> None:
    event = _event(1600)
    readings = MemoryReadings()
    results = MemoryResults()
    service = CountingService()

    first = await process_accepted_reading(
        event,
        readings=readings,
        results=results,
        service=service,
    )
    second = await process_accepted_reading(
        event,
        readings=readings,
        results=results,
        service=service,
    )

    assert second == first
    assert service.calls == 1
    assert results.saves == 1
    assert len(readings.saved) == 1


async def test_non_finite_power_is_permanent() -> None:
    event = ReadingAccepted.model_construct(
        reading_id=uuid4(),
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=float("inf"),
    )
    readings = MemoryReadings()
    results = MemoryResults()

    with pytest.raises(InvalidReadingError):
        await process_accepted_reading(
            event,
            readings=readings,
            results=results,
            service=EnergyDisaggregationService(),
        )

    assert readings.saved == []
    assert results.saves == 0
