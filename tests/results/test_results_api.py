from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from results_service.app import create_app
from results_service.reading import ProcessedReading

READING_ID = UUID("98cc0f71-3296-44b5-a082-e87c1ed5357e")
TIMESTAMP = datetime(2026, 9, 30, 22, 25, tzinfo=timezone.utc)


class MemoryReader:
    def __init__(self, found: ProcessedReading | None) -> None:
        self.found = found
        self.calls: list[UUID] = []

    async def find(self, reading_id: UUID) -> ProcessedReading | None:
        self.calls.append(reading_id)
        if self.found is None or self.found.reading_id != reading_id:
            return None
        return self.found


def test_health_returns_the_request_id() -> None:
    client = TestClient(create_app(reader=MemoryReader(None)))

    response = client.get("/health", headers={"X-Request-ID": "req-results"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-results"


def test_health() -> None:
    response = TestClient(create_app(reader=MemoryReader(None))).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_result_returns_the_stored_split() -> None:
    stored = ProcessedReading(
        reading_id=READING_ID,
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=1600,
        refrigerator_watts=0,
        air_conditioner_watts=1500,
        water_heater_watts=0,
        other_watts=100,
    )
    client = TestClient(create_app(reader=MemoryReader(stored)))

    response = client.get(f"/results/{READING_ID}")

    assert response.status_code == 200
    assert response.json()["reading_id"] == str(READING_ID)
    assert response.json()["air_conditioner_watts"] == 1500.0
    assert response.json()["other_watts"] == 100.0
    assert response.json()["sensor_id"] == "sensor-001"


def test_get_result_returns_404_when_the_reading_is_not_processed() -> None:
    client = TestClient(create_app(reader=MemoryReader(None)))

    response = client.get(f"/results/{uuid4()}")

    assert response.status_code == 404
