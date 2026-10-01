"""Deterministic energy disaggregation.

The refrigerator, air conditioner, and water heater are treated as on/off loads
with a fixed typical power. Every combination is considered, and the one whose
typical power is the largest value that does not exceed the meter reading is
kept. The unexplained remainder is ``other``.

Each appliance estimate is therefore either 0 W or that appliance's typical
power, and the four estimates sum to the original total. If two combinations
explain the same power, the lowest bitmask wins: refrigerator is preferred,
then air conditioner, then water heater.
"""

import asyncio
import math
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from energyflow_contracts.readings import EnergyReading, SensorId


def _require_finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("power must be finite")
    return value


Watts = Annotated[float, Field(ge=0), AfterValidator(_require_finite)]

_SUM_TOLERANCE_WATTS = 1e-6


class ApplianceSignature(BaseModel):
    """Typical on-power for each disaggregated appliance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    refrigerator_watts: Watts = 150.0
    air_conditioner_watts: Watts = 1_500.0
    water_heater_watts: Watts = 4_500.0


DEFAULT_SIGNATURE = ApplianceSignature()


class DisaggregationInput(BaseModel):
    """Total meter power to split across appliances."""

    model_config = ConfigDict(extra="forbid")

    total_power_watts: Watts


class DisaggregatedPower(BaseModel):
    """Appliance estimates that sum to the measured total."""

    model_config = ConfigDict(extra="forbid")

    total_power_watts: Watts
    refrigerator_watts: Watts
    air_conditioner_watts: Watts
    water_heater_watts: Watts
    other_watts: Watts

    @model_validator(mode="after")
    def estimates_match_total(self) -> Self:
        allocated = (
            self.refrigerator_watts
            + self.air_conditioner_watts
            + self.water_heater_watts
            + self.other_watts
        )
        if abs(allocated - self.total_power_watts) > _SUM_TOLERANCE_WATTS:
            raise ValueError("estimated power must add up to total power")
        return self


class DisaggregatedReading(BaseModel):
    """A meter reading plus the appliance split for that instant."""

    model_config = ConfigDict(extra="forbid")

    sensor_id: SensorId
    timestamp: AwareDatetime
    breakdown: DisaggregatedPower


def split_power(
    sample: DisaggregationInput,
    signature: ApplianceSignature = DEFAULT_SIGNATURE,
) -> DisaggregatedPower:
    """Split ``sample`` into appliance estimates using ``signature``."""
    levels = (
        signature.refrigerator_watts,
        signature.air_conditioner_watts,
        signature.water_heater_watts,
    )
    total = sample.total_power_watts
    best_mask = 0
    best_sum = 0.0

    for mask in range(1, 1 << len(levels)):
        subset = sum(
            watts for bit, watts in enumerate(levels) if mask & (1 << bit)
        )
        if subset <= total and subset > best_sum:
            best_mask = mask
            best_sum = subset

    refrigerator, air_conditioner, water_heater = (
        watts if best_mask & (1 << bit) else 0.0
        for bit, watts in enumerate(levels)
    )
    return DisaggregatedPower(
        total_power_watts=total,
        refrigerator_watts=refrigerator,
        air_conditioner_watts=air_conditioner,
        water_heater_watts=water_heater,
        other_watts=total - best_sum,
    )


class EnergyDisaggregationService:
    """Turn a meter reading into an appliance-level power estimate.

    ``split_power`` stays synchronous. It runs on a worker thread so this
    method can be awaited without blocking the event loop.
    """

    def __init__(self, signature: ApplianceSignature = DEFAULT_SIGNATURE) -> None:
        self._signature = signature

    async def disaggregate(self, reading: EnergyReading) -> DisaggregatedReading:
        sample = DisaggregationInput(total_power_watts=reading.power_watts)
        breakdown = await asyncio.to_thread(split_power, sample, self._signature)
        return DisaggregatedReading(
            sensor_id=reading.sensor_id,
            timestamp=reading.timestamp,
            breakdown=breakdown,
        )
