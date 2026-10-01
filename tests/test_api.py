from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from energyflow.api.app import create_app
from energyflow.models import EnergyReading
from energyflow.persistence.repository import StoredEnergyReading

VALID_READING = {
    "sensor_id": "sensor-001",
    "timestamp": "2026-09-29T10:00:00Z",
    "power_watts": 1600,
}


class MemoryReadings:
    def __init__(self) -> None:
        self.saved: list[StoredEnergyReading] = []

    async def save(self, reading: EnergyReading) -> StoredEnergyReading:
        stored = StoredEnergyReading(
            id=uuid4(),
            sensor_id=reading.sensor_id,
            timestamp=reading.timestamp,
            power_watts=reading.power_watts,
        )
        self.saved.append(stored)
        return stored

    async def find_by_id(self, reading_id: UUID) -> StoredEnergyReading | None:
        for stored in self.saved:
            if stored.id == reading_id:
                return stored
        return None

    async def list_by_sensor(self, sensor_id: str) -> list[StoredEnergyReading]:
        return [stored for stored in self.saved if stored.sensor_id == sensor_id]


class MemoryJobs:
    def __init__(self) -> None:
        self.reading_ids: list[UUID] = []

    async def dispatch(self, reading_id: UUID) -> None:
        self.reading_ids.append(reading_id)


@pytest.fixture
def readings() -> MemoryReadings:
    return MemoryReadings()


@pytest.fixture
def jobs() -> MemoryJobs:
    return MemoryJobs()


@pytest.fixture
def client(readings: MemoryReadings, jobs: MemoryJobs) -> TestClient:
    return TestClient(create_app(readings=readings, jobs=jobs))


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_requires_readings_and_jobs_together(readings: MemoryReadings) -> None:
    with pytest.raises(ValueError):
        create_app(readings=readings)


def test_post_reading_stores_and_enqueues(
    client: TestClient,
    readings: MemoryReadings,
    jobs: MemoryJobs,
) -> None:
    response = client.post("/readings", json=VALID_READING)

    assert response.status_code == 202
    body = response.json()
    assert body["sensor_id"] == "sensor-001"
    assert body["timestamp"] == "2026-09-29T10:00:00Z"
    assert body["power_watts"] == 1600.0
    assert body["status"] == "accepted"
    assert len(readings.saved) == 1
    assert jobs.reading_ids == [readings.saved[0].id]
    assert body["id"] == str(readings.saved[0].id)
    assert readings.saved[0].timestamp == datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sensor_id": "bad id",
            "timestamp": "2026-09-29T10:00:00Z",
            "power_watts": 1600,
        },
        {
            "sensor_id": "sensor-001",
            "timestamp": "2026-09-29T10:00:00Z",
            "power_watts": -1,
        },
        {
            "sensor_id": "sensor-001",
            "timestamp": "2026-09-29T10:00:00",
            "power_watts": 1600,
        },
        {
            "timestamp": "2026-09-29T10:00:00Z",
            "power_watts": 1600,
        },
        {
            "sensor_id": "sensor-001",
            "timestamp": "2026-09-29T10:00:00Z",
            "power_watts": 1600,
            "site": "north",
        },
    ],
)
def test_post_reading_rejects_invalid_body(
    client: TestClient,
    readings: MemoryReadings,
    jobs: MemoryJobs,
    payload: dict[str, object],
) -> None:
    response = client.post("/readings", json=payload)

    assert response.status_code == 422
    assert readings.saved == []
    assert jobs.reading_ids == []
