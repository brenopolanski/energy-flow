"""Processing stores a result that the results service can read.

These tests need PostgreSQL. Set ENERGYFLOW_DATABASE_URL or use
``postgresql:///energyflow_test``.
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from energyflow_contracts.events import ReadingAccepted
from energyflow_contracts.readings import EnergyReading
from processing_service.domain import EnergyDisaggregationService
from processing_service.persistence.postgres import (
    DEFAULT_DATABASE_URL,
    PostgresDisaggregationResultRepository,
    PostgresEnergyReadingRepository,
    connect,
)
from processing_service.use_case import process_accepted_reading
from results_service.postgres import PostgresResultReader

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("ENERGYFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)
TIMESTAMP = datetime(2026, 9, 30, 22, 25, tzinfo=timezone.utc)


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


async def test_a_processed_event_is_readable_once(pool) -> None:
    event = ReadingAccepted.from_reading(
        uuid4(),
        EnergyReading(sensor_id="sensor-001", timestamp=TIMESTAMP, power_watts=1600),
    )
    readings = PostgresEnergyReadingRepository(pool)
    results = PostgresDisaggregationResultRepository(pool)
    service = EnergyDisaggregationService()

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
    found = await PostgresResultReader(pool).find(event.reading_id)
    count = await pool.fetchval("SELECT count(*) FROM disaggregation_results")

    assert second.reading_id == first.reading_id
    assert found is not None
    assert found.reading_id == event.reading_id
    assert found.sensor_id == "sensor-001"
    assert found.power_watts == 1600
    assert found.air_conditioner_watts == 1500
    assert found.other_watts == 100
    assert count == 1
