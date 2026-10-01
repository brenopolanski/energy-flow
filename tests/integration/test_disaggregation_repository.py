"""Disaggregation results stored in PostgreSQL.

These tests need a running PostgreSQL database. Set ENERGYFLOW_DATABASE_URL
or accept the default local database ``energyflow_test``.
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from energyflow.disaggregation import DisaggregatedPower, DisaggregatedReading, EnergyDisaggregationService
from energyflow.models import EnergyReading
from energyflow.persistence.postgres import (
    DEFAULT_DATABASE_URL,
    PostgresDisaggregationResultRepository,
    PostgresEnergyReadingRepository,
    connect,
)
from energyflow.processing import ReadingNotFoundError, process_stored_reading

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("ENERGYFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)
TIMESTAMP = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def pool():
    try:
        opened = await connect(DATABASE_URL)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    async with opened.acquire() as connection:
        await connection.execute("TRUNCATE disaggregation_results, energy_readings")
    try:
        yield opened
    finally:
        await opened.close()


def _reading() -> EnergyReading:
    return EnergyReading(
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=1600,
    )


def _other_split(reading: EnergyReading) -> DisaggregatedReading:
    return DisaggregatedReading(
        sensor_id=reading.sensor_id,
        timestamp=reading.timestamp,
        breakdown=DisaggregatedPower(
            total_power_watts=1600,
            refrigerator_watts=0,
            air_conditioner_watts=0,
            water_heater_watts=0,
            other_watts=1600,
        ),
    )


async def test_saving_the_same_reading_twice_keeps_the_first_result(pool) -> None:
    readings = PostgresEnergyReadingRepository(pool)
    results = PostgresDisaggregationResultRepository(pool)
    stored = await readings.save(_reading())
    service = EnergyDisaggregationService()
    disaggregated = await service.disaggregate(
        EnergyReading(
            sensor_id=stored.sensor_id,
            timestamp=stored.timestamp,
            power_watts=stored.power_watts,
        )
    )

    first = await results.save(stored.id, disaggregated)
    second = await results.save(stored.id, _other_split(stored))
    found = await results.find_by_reading_id(stored.id)
    count = await pool.fetchval(
        "SELECT count(*) FROM disaggregation_results WHERE reading_id = $1",
        stored.id,
    )

    assert second == first
    assert found == first
    assert first.breakdown.air_conditioner_watts == 1500
    assert second.breakdown.other_watts == 100
    assert count == 1


async def test_processing_persists_one_result_when_run_twice(pool) -> None:
    readings = PostgresEnergyReadingRepository(pool)
    results = PostgresDisaggregationResultRepository(pool)
    stored = await readings.save(_reading())
    service = EnergyDisaggregationService()

    first = await process_stored_reading(
        stored.id,
        readings=readings,
        results=results,
        service=service,
    )
    second = await process_stored_reading(
        stored.id,
        readings=readings,
        results=results,
        service=service,
    )
    count = await pool.fetchval("SELECT count(*) FROM disaggregation_results")

    assert second == first
    assert first.breakdown.air_conditioner_watts == 1500
    assert first.breakdown.other_watts == 100
    assert count == 1


async def test_processing_a_missing_reading_is_permanent(pool) -> None:
    readings = PostgresEnergyReadingRepository(pool)
    results = PostgresDisaggregationResultRepository(pool)

    with pytest.raises(ReadingNotFoundError):
        await process_stored_reading(
            uuid4(),
            readings=readings,
            results=results,
            service=EnergyDisaggregationService(),
        )
