"""Repository contract for a stored disaggregation result.

Callers depend on this protocol. They do not import a database driver.
"""

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from processing_service.domain import DisaggregatedPower, DisaggregatedReading
from energyflow_contracts.readings import SensorId


class StoredDisaggregation(BaseModel):
    """The appliance split stored for one reading."""

    model_config = ConfigDict(extra="forbid")

    reading_id: UUID
    sensor_id: SensorId
    timestamp: AwareDatetime
    breakdown: DisaggregatedPower


class DisaggregationResultRepository(Protocol):
    """Loads and stores one disaggregation per reading."""

    async def find_by_reading_id(self, reading_id: UUID) -> StoredDisaggregation | None:
        """Return the stored split for ``reading_id``, or ``None`` when absent."""

    async def save(
        self,
        reading_id: UUID,
        result: DisaggregatedReading,
    ) -> StoredDisaggregation:
        """Store ``result`` for ``reading_id`` and return the stored row.

        A second save for the same reading returns the row already stored.
        """
