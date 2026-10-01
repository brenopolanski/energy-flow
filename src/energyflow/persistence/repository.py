"""Repository contract for stored energy readings.

Callers depend on this protocol. They do not import a database driver.
"""

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from energyflow.models import EnergyReading, SensorId


class StoredEnergyReading(BaseModel):
    """An energy reading that has been stored and given an id."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    sensor_id: SensorId
    timestamp: AwareDatetime
    power_watts: float = Field(ge=0)


class EnergyReadingRepository(Protocol):
    """Saves and loads energy readings without exposing how they are stored."""

    async def save(self, reading: EnergyReading) -> StoredEnergyReading:
        """Store ``reading`` and return it with the id assigned by storage."""

    async def find_by_id(self, reading_id: UUID) -> StoredEnergyReading | None:
        """Return the reading with ``reading_id``, or ``None`` when it is absent."""

    async def list_by_sensor(self, sensor_id: str) -> list[StoredEnergyReading]:
        """Return readings for ``sensor_id``, oldest first."""
