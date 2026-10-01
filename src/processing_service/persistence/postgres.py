"""PostgreSQL implementation of the energy-reading repository."""

import math
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

from processing_service.domain import DisaggregatedPower, DisaggregatedReading
from energyflow_contracts.readings import EnergyReading
from processing_service.persistence.repository import StoredEnergyReading
from processing_service.persistence.results import StoredDisaggregation

DEFAULT_DATABASE_URL = "postgresql:///energyflow_test"

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_INSERT = """
INSERT INTO energy_readings (sensor_id, recorded_at, power_watts)
VALUES ($1, $2, $3)
RETURNING id, sensor_id, recorded_at, power_watts
"""

_INSERT_WITH_ID = """
INSERT INTO energy_readings (id, sensor_id, recorded_at, power_watts)
VALUES ($1, $2, $3, $4)
ON CONFLICT (id) DO NOTHING
RETURNING id, sensor_id, recorded_at, power_watts
"""

_SELECT_BY_ID = """
SELECT id, sensor_id, recorded_at, power_watts
FROM energy_readings
WHERE id = $1
"""

_SELECT_BY_SENSOR = """
SELECT id, sensor_id, recorded_at, power_watts
FROM energy_readings
WHERE sensor_id = $1
ORDER BY recorded_at ASC, id ASC
"""


class PostgresEnergyReadingRepository:
    """Stores readings in the ``energy_readings`` table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(self, reading: EnergyReading) -> StoredEnergyReading:
        _require_storable(reading)
        row = await self._pool.fetchrow(
            _INSERT,
            reading.sensor_id,
            reading.timestamp,
            reading.power_watts,
        )
        assert row is not None
        return _to_reading(row)

    async def save_with_id(self, reading_id: UUID, reading: EnergyReading) -> StoredEnergyReading:
        """Store ``reading`` under ``reading_id``. A second insert keeps the first row."""
        _require_storable(reading)
        row = await self._pool.fetchrow(
            _INSERT_WITH_ID,
            reading_id,
            reading.sensor_id,
            reading.timestamp,
            reading.power_watts,
        )
        if row is not None:
            return _to_reading(row)
        existing = await self.find_by_id(reading_id)
        if existing is None:
            raise RuntimeError(f"reading {reading_id} disappeared during save")
        return existing

    async def find_by_id(self, reading_id: UUID) -> StoredEnergyReading | None:
        row = await self._pool.fetchrow(_SELECT_BY_ID, reading_id)
        if row is None:
            return None
        return _to_reading(row)

    async def list_by_sensor(self, sensor_id: str) -> list[StoredEnergyReading]:
        rows = await self._pool.fetch(_SELECT_BY_SENSOR, sensor_id)
        return [_to_reading(row) for row in rows]


async def apply_schema(pool: asyncpg.Pool) -> None:
    """Create the readings table when it is not already present."""
    schema = _SCHEMA_PATH.read_text()
    async with pool.acquire() as connection:
        await connection.execute(schema)


async def connect(database_url: str) -> asyncpg.Pool:
    """Open a pool and ensure the schema exists."""
    pool = await asyncpg.create_pool(database_url)
    try:
        await apply_schema(pool)
    except Exception:
        await pool.close()
        raise
    return pool


def _require_storable(reading: EnergyReading) -> None:
    if not _is_aware(reading.timestamp):
        raise ValueError("timestamp must be timezone-aware")
    if reading.power_watts < 0 or not math.isfinite(reading.power_watts):
        raise ValueError("power must be finite and greater than or equal to zero")


def _is_aware(timestamp: datetime) -> bool:
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def _to_reading(row: asyncpg.Record) -> StoredEnergyReading:
    return StoredEnergyReading(
        id=row["id"],
        sensor_id=row["sensor_id"],
        timestamp=row["recorded_at"],
        power_watts=row["power_watts"],
    )


_INSERT_RESULT = """
INSERT INTO disaggregation_results (
    reading_id,
    total_power_watts,
    refrigerator_watts,
    air_conditioner_watts,
    water_heater_watts,
    other_watts
)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (reading_id) DO NOTHING
RETURNING
    reading_id,
    total_power_watts,
    refrigerator_watts,
    air_conditioner_watts,
    water_heater_watts,
    other_watts
"""

_SELECT_RESULT = """
SELECT
    reading.id,
    reading.sensor_id,
    reading.recorded_at,
    result.total_power_watts,
    result.refrigerator_watts,
    result.air_conditioner_watts,
    result.water_heater_watts,
    result.other_watts
FROM disaggregation_results AS result
JOIN energy_readings AS reading ON reading.id = result.reading_id
WHERE result.reading_id = $1
"""


class PostgresDisaggregationResultRepository:
    """Stores one appliance split per reading."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def find_by_reading_id(self, reading_id: UUID) -> StoredDisaggregation | None:
        row = await self._pool.fetchrow(_SELECT_RESULT, reading_id)
        if row is None:
            return None
        return _to_result(row)

    async def save(
        self,
        reading_id: UUID,
        result: DisaggregatedReading,
    ) -> StoredDisaggregation:
        breakdown = result.breakdown
        inserted = await self._pool.fetchrow(
            _INSERT_RESULT,
            reading_id,
            breakdown.total_power_watts,
            breakdown.refrigerator_watts,
            breakdown.air_conditioner_watts,
            breakdown.water_heater_watts,
            breakdown.other_watts,
        )
        if inserted is not None:
            return _stored_from_insert(result, inserted)
        existing = await self.find_by_reading_id(reading_id)
        if existing is None:
            raise RuntimeError(f"disaggregation for {reading_id} disappeared during save")
        return existing


def _stored_from_insert(
    result: DisaggregatedReading,
    row: asyncpg.Record,
) -> StoredDisaggregation:
    return StoredDisaggregation(
        reading_id=row["reading_id"],
        sensor_id=result.sensor_id,
        timestamp=result.timestamp,
        breakdown=_breakdown(row),
    )


def _to_result(row: asyncpg.Record) -> StoredDisaggregation:
    return StoredDisaggregation(
        reading_id=row["id"],
        sensor_id=row["sensor_id"],
        timestamp=row["recorded_at"],
        breakdown=_breakdown(row),
    )


def _breakdown(row: asyncpg.Record) -> DisaggregatedPower:
    return DisaggregatedPower(
        total_power_watts=row["total_power_watts"],
        refrigerator_watts=row["refrigerator_watts"],
        air_conditioner_watts=row["air_conditioner_watts"],
        water_heater_watts=row["water_heater_watts"],
        other_watts=row["other_watts"],
    )
