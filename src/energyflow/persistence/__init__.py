"""Persistence ports for EnergyFlow.

This package exposes the repository contract. PostgreSQL lives in
``energyflow.persistence.postgres`` and is not imported here.
"""

from energyflow.persistence.repository import (
    EnergyReadingRepository,
    StoredEnergyReading,
)
from energyflow.persistence.results import (
    DisaggregationResultRepository,
    StoredDisaggregation,
)

__all__ = [
    "DisaggregationResultRepository",
    "EnergyReadingRepository",
    "StoredDisaggregation",
    "StoredEnergyReading",
]
