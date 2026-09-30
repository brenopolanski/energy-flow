import pytest
from fastapi.testclient import TestClient

from energyflow.api.app import create_app

VALID_READING = {
    "sensor_id": "sensor-001",
    "timestamp": "2026-09-29T10:00:00Z",
    "power_watts": 1600,
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("power_watts", "breakdown"),
    [
        (
            1600,
            {
                "total_power_watts": 1600.0,
                "refrigerator_watts": 0.0,
                "air_conditioner_watts": 1500.0,
                "water_heater_watts": 0.0,
                "other_watts": 100.0,
            },
        ),
        (
            6150,
            {
                "total_power_watts": 6150.0,
                "refrigerator_watts": 150.0,
                "air_conditioner_watts": 1500.0,
                "water_heater_watts": 4500.0,
                "other_watts": 0.0,
            },
        ),
    ],
)
def test_post_reading_returns_disaggregation(
    client: TestClient,
    power_watts: float,
    breakdown: dict[str, float],
) -> None:
    response = client.post(
        "/readings",
        json={**VALID_READING, "power_watts": power_watts},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sensor_id"] == "sensor-001"
    assert body["timestamp"] == "2026-09-29T10:00:00Z"
    assert body["breakdown"] == breakdown


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
    payload: dict[str, object],
) -> None:
    response = client.post("/readings", json=payload)

    assert response.status_code == 422
