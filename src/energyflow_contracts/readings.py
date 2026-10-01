"""The reading shape accepted at the service boundary.

This is a contract. It does not disaggregate, store, or publish.
"""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SensorId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        description="Letters, digits, '_' and '-'. Must start with a letter or digit.",
    ),
]


class EnergyReading(BaseModel):
    """One instantaneous power measurement from a sensor."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sensor_id: SensorId
    timestamp: AwareDatetime
    power_watts: Annotated[float, Field(ge=0)]
