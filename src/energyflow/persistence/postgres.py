"""PostgreSQL implementation of the energy-reading repository."""

import math
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

from energyflow.models import EnergyReading
from energyflow.persistence.repository import StoredEnergyReading

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_INSERT = """
INSERT INTO energy_readings (sensor_id, recorded_at, power_watts)
VALUES ($1, $2, $3)
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
