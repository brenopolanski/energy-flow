from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from energyflow.disaggregation import (
    ApplianceSignature,
    DisaggregatedPower,
    DisaggregationInput,
    EnergyDisaggregationService,
    split_power,
)
from energyflow.models import EnergyReading

TIMESTAMP = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _split(total_power_watts: float, signature: ApplianceSignature | None = None):
    sample = DisaggregationInput(total_power_watts=total_power_watts)
    if signature is None:
        return split_power(sample)
    return split_power(sample, signature)


def test_zero_power_assigns_nothing() -> None:
    power = _split(0)

    assert power.refrigerator_watts == 0
    assert power.air_conditioner_watts == 0
    assert power.water_heater_watts == 0
    assert power.other_watts == 0


@pytest.mark.parametrize(
    ("total", "refrigerator", "air_conditioner", "water_heater", "other"),
    [
        (100, 0, 0, 0, 100),
        (150, 150, 0, 0, 0),
        (200, 150, 0, 0, 50),
        (1_500, 0, 1_500, 0, 0),
        (1_600, 0, 1_500, 0, 100),
        (1_650, 150, 1_500, 0, 0),
        (4_500, 0, 0, 4_500, 0),
        (4_650, 150, 0, 4_500, 0),
        (6_000, 0, 1_500, 4_500, 0),
        (6_150, 150, 1_500, 4_500, 0),
        (10_000, 150, 1_500, 4_500, 3_850),
        (150.25, 150, 0, 0, 0.25),
    ],
)
def test_selects_the_largest_signature_that_fits(
    total: float,
    refrigerator: float,
    air_conditioner: float,
    water_heater: float,
    other: float,
) -> None:
    power = _split(total)

    assert power.refrigerator_watts == refrigerator
    assert power.air_conditioner_watts == air_conditioner
    assert power.water_heater_watts == water_heater
    assert power.other_watts == pytest.approx(other)
    assert (
        power.refrigerator_watts
        + power.air_conditioner_watts
        + power.water_heater_watts
        + power.other_watts
    ) == pytest.approx(total)


@pytest.mark.parametrize("total", [0, 1, 149.9, 151, 1_649, 4_499, 6_149.5, 20_000])
def test_estimates_are_non_negative_and_sum_to_total(total: float) -> None:
    power = _split(total)
    parts = (
        power.refrigerator_watts,
        power.air_conditioner_watts,
        power.water_heater_watts,
        power.other_watts,
    )

    assert all(part >= 0 for part in parts)
    assert sum(parts) == pytest.approx(total)
    assert power.refrigerator_watts in (0, 150)
    assert power.air_conditioner_watts in (0, 1_500)
    assert power.water_heater_watts in (0, 4_500)


def test_same_input_always_returns_the_same_split() -> None:
    assert _split(2_345.5) == _split(2_345.5)


def test_tie_prefers_the_earlier_appliance() -> None:
    signature = ApplianceSignature(
        refrigerator_watts=100,
        air_conditioner_watts=100,
        water_heater_watts=0,
    )

    power = _split(100, signature)

    assert power.refrigerator_watts == 100
    assert power.air_conditioner_watts == 0
    assert power.water_heater_watts == 0
    assert power.other_watts == 0


@pytest.mark.parametrize("total", [-1, -0.1, float("nan"), float("inf")])
def test_rejects_invalid_totals(total: float) -> None:
    with pytest.raises(ValidationError):
        DisaggregationInput(total_power_watts=total)


def test_rejects_negative_signature_power() -> None:
    with pytest.raises(ValidationError):
        ApplianceSignature(refrigerator_watts=-150)


def test_rejects_breakdown_that_does_not_sum_to_total() -> None:
    with pytest.raises(ValidationError):
        DisaggregatedPower(
            total_power_watts=100,
            refrigerator_watts=150,
            air_conditioner_watts=0,
            water_heater_watts=0,
            other_watts=0,
        )


def test_rejects_negative_appliance_estimate() -> None:
    with pytest.raises(ValidationError):
        DisaggregatedPower(
            total_power_watts=100,
            refrigerator_watts=-10,
            air_conditioner_watts=0,
            water_heater_watts=0,
            other_watts=110,
        )


def test_service_attaches_the_split_to_the_reading() -> None:
    reading = EnergyReading(
        sensor_id="meter-1",
        timestamp=TIMESTAMP,
        power_watts=1_650,
    )

    result = EnergyDisaggregationService().disaggregate(reading)

    assert result.sensor_id == "meter-1"
    assert result.timestamp == TIMESTAMP
    assert result.breakdown == _split(1_650)


def test_service_uses_the_injected_signature() -> None:
    reading = EnergyReading(
        sensor_id="meter-1",
        timestamp=TIMESTAMP,
        power_watts=80,
    )
    signature = ApplianceSignature(
        refrigerator_watts=40,
        air_conditioner_watts=30,
        water_heater_watts=20,
    )

    result = EnergyDisaggregationService(signature).disaggregate(reading)

    assert result.breakdown.refrigerator_watts == 40
    assert result.breakdown.air_conditioner_watts == 30
    assert result.breakdown.water_heater_watts == 0
    assert result.breakdown.other_watts == pytest.approx(10)


def test_service_rejects_non_finite_power_on_the_reading() -> None:
    reading = EnergyReading.model_construct(
        sensor_id="meter-1",
        timestamp=TIMESTAMP,
        power_watts=float("inf"),
    )

    with pytest.raises(ValidationError):
        EnergyDisaggregationService().disaggregate(reading)
