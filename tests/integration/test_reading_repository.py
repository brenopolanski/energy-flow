"""Integration tests for the PostgreSQL energy-reading repository.

These tests need a running PostgreSQL database. Set ENERGYFLOW_DATABASE_URL
or accept the default local database ``energyflow_test``.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from energyflow.models import EnergyReading
from energyflow.persistence.postgres import PostgresEnergyReadingRepository, connect

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "ENERGYFLOW_DATABASE_URL",
    "postgresql:///energyflow_test",
)


@pytest_asyncio.fixture
async def pool():
    try:
        opened = await connect(DATABASE_URL)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    async with opened.acquire() as connection:
        await connection.execute("TRUNCATE energy_readings")
    try:
        yield opened
    finally:
        await opened.close()


@pytest_asyncio.fixture
async def repository(pool: asyncpg.Pool) -> PostgresEnergyReadingRepository:
    return PostgresEnergyReadingRepository(pool)


def _reading(
    sensor_id: str,
    power_watts: float,
    timestamp: datetime | None = None,
) -> EnergyReading:
    return EnergyReading(
        sensor_id=sensor_id,
        timestamp=timestamp or datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        power_watts=power_watts,
    )


async def test_save_and_find_by_id(repository: PostgresEnergyReadingRepository) -> None:
    reading = _reading("sensor-001", 1600)

    stored = await repository.save(reading)
    found = await repository.find_by_id(stored.id)

    assert found is not None
    assert found.id == stored.id
    assert found.sensor_id == "sensor-001"
    assert found.timestamp == reading.timestamp
    assert found.power_watts == 1600


async def test_find_by_id_returns_none_when_missing(
    repository: PostgresEnergyReadingRepository,
) -> None:
    assert await repository.find_by_id(uuid4()) is None


async def test_list_by_sensor_returns_that_sensor_oldest_first(
    repository: PostgresEnergyReadingRepository,
) -> None:
    later = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    earlier = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
    await repository.save(_reading("sensor-001", 100, earlier))
    await repository.save(_reading("sensor-002", 999, earlier))
    await repository.save(_reading("sensor-001", 200, later))

    listed = await repository.list_by_sensor("sensor-001")

    assert [item.power_watts for item in listed] == [100, 200]
    assert [item.timestamp for item in listed] == [earlier, later]
    assert {item.sensor_id for item in listed} == {"sensor-001"}


async def test_list_by_sensor_is_empty_when_sensor_has_no_readings(
    repository: PostgresEnergyReadingRepository,
) -> None:
    await repository.save(_reading("sensor-001", 100))

    assert await repository.list_by_sensor("sensor-002") == []


async def test_save_preserves_a_non_utc_timestamp(
    repository: PostgresEnergyReadingRepository,
) -> None:
    recorded_at = datetime(2026, 9, 29, 7, 0, tzinfo=timezone(timedelta(hours=-3)))
    reading = _reading("sensor-001", 1500, recorded_at)

    stored = await repository.save(reading)

    assert stored.timestamp == recorded_at
    assert stored.timestamp.tzinfo is not None


async def test_save_rejects_naive_timestamp(
    repository: PostgresEnergyReadingRepository,
) -> None:
    reading = EnergyReading.model_construct(
        sensor_id="sensor-001",
        timestamp=datetime(2026, 9, 29, 10, 0),
        power_watts=10,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        await repository.save(reading)


async def test_save_rejects_non_finite_power(
    repository: PostgresEnergyReadingRepository,
) -> None:
    reading = EnergyReading.model_construct(
        sensor_id="sensor-001",
        timestamp=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        power_watts=float("inf"),
    )

    with pytest.raises(ValueError, match="finite"):
        await repository.save(reading)


async def test_database_rejects_negative_power_and_invalid_sensor_id(
    pool: asyncpg.Pool,
) -> None:
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO energy_readings (sensor_id, recorded_at, power_watts)
                VALUES ($1, $2, $3)
                """,
                "sensor-001",
                datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
                -100,
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO energy_readings (sensor_id, recorded_at, power_watts)
                VALUES ($1, $2, $3)
                """,
                "bad id",
                datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
                10,
            )
