from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from energyflow.messaging.events import EnergyReadingAccepted
from energyflow.messaging.rabbitmq import handle_delivery
from energyflow.models import EnergyReading

TIMESTAMP = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


def _reading() -> EnergyReading:
    return EnergyReading(
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=1600,
    )


def test_event_serializes_to_json_and_back() -> None:
    event = EnergyReadingAccepted.from_reading(_reading())

    restored = EnergyReadingAccepted.from_json(event.to_json())

    assert restored == event
    assert restored.event_type == "energy_reading.accepted"
    assert restored.power_watts == 1600


def test_from_json_rejects_malformed_payloads() -> None:
    with pytest.raises(ValidationError):
        EnergyReadingAccepted.from_json("{")
    with pytest.raises(ValidationError):
        EnergyReadingAccepted.from_json(b'{"sensor_id": "bad id"}')
    with pytest.raises(ValidationError):
        EnergyReadingAccepted.from_json(
            b'{"event_type":"other","sensor_id":"sensor-001",'
            b'"timestamp":"2026-09-29T10:00:00Z","power_watts":1}'
        )


class _Message:
    def __init__(self, body: bytes, headers: dict[str, object] | None = None) -> None:
        self.body = body
        self.headers = headers
        self.acked = False
        self.requeue: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.requeue = requeue


class _Republish:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, int]] = []

    async def __call__(self, body: bytes, attempt: int) -> None:
        self.calls.append((body, attempt))


async def _ok(_event: EnergyReadingAccepted) -> None:
    return None


async def test_delivery_acks_a_valid_event() -> None:
    event = EnergyReadingAccepted.from_reading(_reading())
    message = _Message(event.to_json().encode())
    republish = _Republish()

    await handle_delivery(message, handler=_ok, republish=republish)

    assert message.acked is True
    assert message.requeue is None
    assert republish.calls == []


async def test_delivery_drops_malformed_json_without_requeue() -> None:
    message = _Message(b"not-json")
    republish = _Republish()

    await handle_delivery(message, handler=_ok, republish=republish)

    assert message.acked is False
    assert message.requeue is False
    assert republish.calls == []


async def test_delivery_retries_then_drops_after_the_last_attempt() -> None:
    event = EnergyReadingAccepted.from_reading(_reading())
    body = event.to_json().encode()
    republish = _Republish()

    async def fail(_event: EnergyReadingAccepted) -> None:
        raise RuntimeError("temporary")

    first = _Message(body)
    await handle_delivery(first, handler=fail, republish=republish, max_attempts=3)
    assert first.acked is True
    assert republish.calls == [(body, 2)]

    second = _Message(body, {"x-attempt": 2})
    await handle_delivery(second, handler=fail, republish=republish, max_attempts=3)
    assert second.acked is True
    assert republish.calls == [(body, 2), (body, 3)]

    third = _Message(body, {"x-attempt": 3})
    await handle_delivery(third, handler=fail, republish=republish, max_attempts=3)
    assert third.acked is False
    assert third.requeue is False
    assert republish.calls == [(body, 2), (body, 3)]
