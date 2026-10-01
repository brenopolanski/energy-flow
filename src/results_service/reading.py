"""Read model for one processed reading.

This service owns the query. It does not import the processing service.
"""

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class ProcessedReading(BaseModel):
    """A stored disaggregation, as the results API returns it."""

    model_config = ConfigDict(extra="forbid")

    reading_id: UUID
    sensor_id: str
    timestamp: AwareDatetime
    power_watts: float
    refrigerator_watts: float
    air_conditioner_watts: float
    water_heater_watts: float
    other_watts: float


class ResultReader(Protocol):
    """Loads one processed reading by the id ingestion assigned."""

    async def find(self, reading_id: UUID) -> ProcessedReading | None:
        """Return the processed reading, or ``None`` when it is absent."""
