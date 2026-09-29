from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from energyflow.models import EnergyReading

VALID_TIMESTAMP = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def test_accepts_a_valid_reading() -> None:
    reading = EnergyReading(
        sensor_id="  meter-1 ",
        timestamp=VALID_TIMESTAMP,
        power_watts=1200.5,
    )

    assert reading.sensor_id == "meter-1"
    assert reading.timestamp == VALID_TIMESTAMP
    assert reading.timestamp.tzinfo is not None
    assert reading.power_watts == 1200.5


def test_accepts_zero_power() -> None:
    reading = EnergyReading(
        sensor_id="meter-1",
        timestamp=VALID_TIMESTAMP,
        power_watts=0,
    )

    assert reading.power_watts == 0


def test_rejects_negative_power() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EnergyReading(
            sensor_id="meter-1",
            timestamp=VALID_TIMESTAMP,
            power_watts=-1,
        )

    assert exc_info.value.errors()[0]["loc"] == ("power_watts",)


@pytest.mark.parametrize(
    "sensor_id",
    [
        "",
        "   ",
        "bad id",
        "-meter",
        "meter.1",
        "x" * 65,
    ],
)
def test_rejects_invalid_sensor_id(sensor_id: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        EnergyReading(
            sensor_id=sensor_id,
            timestamp=VALID_TIMESTAMP,
            power_watts=10,
        )

    assert exc_info.value.errors()[0]["loc"] == ("sensor_id",)


def test_serializes_and_round_trips() -> None:
    reading = EnergyReading(
        sensor_id="meter-1",
        timestamp=VALID_TIMESTAMP,
        power_watts=1200.5,
    )

    data = reading.model_dump()
    assert data == {
        "sensor_id": "meter-1",
        "timestamp": VALID_TIMESTAMP,
        "power_watts": 1200.5,
    }

    payload = reading.model_dump(mode="json")
    assert payload["timestamp"] == "2026-09-28T12:00:00Z"
    assert EnergyReading.model_validate(payload) == reading
    assert EnergyReading.model_validate_json(reading.model_dump_json()) == reading


def test_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EnergyReading(
            sensor_id="meter-1",
            timestamp=datetime(2026, 9, 28, 12, 0),
            power_watts=10,
        )

    assert exc_info.value.errors()[0]["loc"] == ("timestamp",)


def test_rejects_missing_fields_and_unknown_fields() -> None:
    with pytest.raises(ValidationError) as missing:
        EnergyReading.model_validate(
            {"timestamp": VALID_TIMESTAMP, "power_watts": 10}
        )
    assert any(error["loc"] == ("sensor_id",) for error in missing.value.errors())

    with pytest.raises(ValidationError) as unknown:
        EnergyReading.model_validate(
            {
                "sensor_id": "meter-1",
                "timestamp": VALID_TIMESTAMP,
                "power_watts": 10,
                "site": "north",
            }
        )
    assert unknown.value.errors()[0]["loc"] == ("site",)


def test_rejects_non_numeric_power() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EnergyReading.model_validate(
            {
                "sensor_id": "meter-1",
                "timestamp": "2026-09-28T12:00:00Z",
                "power_watts": "high",
            }
        )

    assert exc_info.value.errors()[0]["loc"] == ("power_watts",)
