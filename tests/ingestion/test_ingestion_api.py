from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from energyflow_contracts.events import ReadingAccepted
from ingestion_service.app import create_app

VALID_READING = {
    "sensor_id": "sensor-001",
    "timestamp": "2026-09-30T22:25:00Z",
    "power_watts": 1600,
}


class MemoryPublisher:
    def __init__(self) -> None:
        self.events: list[ReadingAccepted] = []

    async def publish(self, event: ReadingAccepted) -> None:
        self.events.append(event)


def test_health() -> None:
    client = TestClient(create_app(publisher=MemoryPublisher()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_reading_publishes_an_accepted_event() -> None:
    publisher = MemoryPublisher()
    client = TestClient(create_app(publisher=publisher))

    response = client.post("/readings", json=VALID_READING)

    assert response.status_code == 202
    body = response.json()
    assert body["sensor_id"] == "sensor-001"
    assert body["timestamp"] == "2026-09-30T22:25:00Z"
    assert body["power_watts"] == 1600.0
    assert body["status"] == "accepted"
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert body["id"] == str(event.reading_id)
    assert event.sensor_id == "sensor-001"
    assert event.power_watts == 1600
    assert event.timestamp == datetime(2026, 9, 30, 22, 25, tzinfo=timezone.utc)
    assert isinstance(event.reading_id, UUID)


def test_post_reading_carries_the_request_id() -> None:
    publisher = MemoryPublisher()
    client = TestClient(create_app(publisher=publisher))

    response = client.post(
        "/readings",
        json=VALID_READING,
        headers={"X-Request-ID": "req-123"},
    )

    assert response.status_code == 202
    assert response.headers["x-request-id"] == "req-123"
    assert publisher.events[0].correlation_id == "req-123"


def test_post_reading_records_a_publish_metric() -> None:
    publisher = MemoryPublisher()
    client = TestClient(create_app(publisher=publisher))

    before = client.get("/metrics")
    posted = client.post("/readings", json=VALID_READING)
    after = client.get("/metrics")

    assert posted.status_code == 202
    assert _counter(before.text, "energyflow_readings_published_total") + 1 == _counter(
        after.text,
        "energyflow_readings_published_total",
    )
    assert 'path="/readings"' in after.text


def _counter(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[-1])
    return 0.0


def test_post_reading_rejects_an_invalid_body_without_publishing() -> None:
    publisher = MemoryPublisher()
    client = TestClient(create_app(publisher=publisher))

    response = client.post(
        "/readings",
        json={**VALID_READING, "power_watts": -1},
    )

    assert response.status_code == 422
    assert publisher.events == []
