from energyflow.readings import total_kwh


def test_total_kwh_sums_readings() -> None:
    assert total_kwh([1.5, 2.0, 0.5]) == 4.0
