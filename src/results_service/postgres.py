"""PostgreSQL reader for processed readings."""

import os
from uuid import UUID

import asyncpg

from results_service.reading import ProcessedReading

DEFAULT_DATABASE_URL = "postgresql:///energyflow_test"

_SELECT = """
SELECT
    reading.id,
    reading.sensor_id,
    reading.recorded_at,
    reading.power_watts,
    result.refrigerator_watts,
    result.air_conditioner_watts,
    result.water_heater_watts,
    result.other_watts
FROM disaggregation_results AS result
JOIN energy_readings AS reading ON reading.id = result.reading_id
WHERE result.reading_id = $1
"""


def database_url() -> str:
    return os.environ.get("ENERGYFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)


class PostgresResultReader:
    """Reads ``disaggregation_results`` joined to ``energy_readings``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def find(self, reading_id: UUID) -> ProcessedReading | None:
        row = await self._pool.fetchrow(_SELECT, reading_id)
        if row is None:
            return None
        return ProcessedReading(
            reading_id=row["id"],
            sensor_id=row["sensor_id"],
            timestamp=row["recorded_at"],
            power_watts=row["power_watts"],
            refrigerator_watts=row["refrigerator_watts"],
            air_conditioner_watts=row["air_conditioner_watts"],
            water_heater_watts=row["water_heater_watts"],
            other_watts=row["other_watts"],
        )


async def connect(database_url: str) -> asyncpg.Pool:
    """Open a pool. The processing service creates the tables."""
    return await asyncpg.create_pool(database_url)
