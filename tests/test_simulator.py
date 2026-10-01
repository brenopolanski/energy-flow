from sensor_simulator.load import percentile, planned_readings, reading_power, sensor_id


def test_planned_readings_cover_every_sensor() -> None:
    bodies = planned_readings(3, 2)

    assert len(bodies) == 6
    assert {body["sensor_id"] for body in bodies} == {
        "sensor-00001",
        "sensor-00002",
        "sensor-00003",
    }
    assert all(isinstance(body["power_watts"], float) and body["power_watts"] >= 0 for body in bodies)
    assert len({body["timestamp"] for body in bodies if body["sensor_id"] == "sensor-00001"}) == 2


def test_sensor_ids_and_power_are_stable() -> None:
    assert sensor_id(1) == "sensor-00001"
    assert reading_power(1, 0) == reading_power(1, 0)
    assert 0 <= percentile([0.1, 0.2, 0.4], 50) <= 0.4
