"""Events published when a reading is accepted."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from energyflow.models import EnergyReading, SensorId

EVENT_TYPE = "energy_reading.accepted"


class EnergyReadingAccepted(BaseModel):
    """A reading that passed validation and was accepted by the API."""

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["energy_reading.accepted"] = EVENT_TYPE
    sensor_id: SensorId
    timestamp: AwareDatetime
    power_watts: Annotated[float, Field(ge=0)]

    @classmethod
    def from_reading(cls, reading: EnergyReading) -> Self:
        return cls(
            sensor_id=reading.sensor_id,
            timestamp=reading.timestamp,
            power_watts=reading.power_watts,
        )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> Self:
        return cls.model_validate_json(payload)
