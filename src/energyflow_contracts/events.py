"""Event published when ingestion accepts a reading."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from energyflow_contracts.readings import EnergyReading, SensorId

PROCESS_READING_TASK = "energyflow.readings.process"
TASK_QUEUE = "energyflow.tasks"


class ReadingAccepted(BaseModel):
    """The payload of one accepted reading.

    Ingestion publishes it. Processing consumes it. The ``reading_id`` is
    assigned by ingestion so a later read can use the same id.
    """

    model_config = ConfigDict(extra="forbid")

    reading_id: UUID
    sensor_id: SensorId
    timestamp: AwareDatetime
    power_watts: Annotated[float, Field(ge=0)]

    @classmethod
    def from_reading(cls, reading_id: UUID, reading: EnergyReading) -> Self:
        return cls(
            reading_id=reading_id,
            sensor_id=reading.sensor_id,
            timestamp=reading.timestamp,
            power_watts=reading.power_watts,
        )

    def to_message(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @classmethod
    def from_message(cls, payload: dict[str, object]) -> Self:
        return cls.model_validate(payload)
