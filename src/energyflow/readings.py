"""Small helpers used while the project skeleton is in place."""


def total_kwh(readings: list[float]) -> float:
    """Return the sum of kilowatt-hour readings."""
    return float(sum(readings))
