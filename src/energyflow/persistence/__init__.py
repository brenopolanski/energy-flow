"""Persistence ports for EnergyFlow.

This package exposes the repository contract. PostgreSQL lives in
``energyflow.persistence.postgres`` and is not imported here.
"""

from energyflow.persistence.repository import (
    EnergyReadingRepository,
    StoredEnergyReading,
)

__all__ = ["EnergyReadingRepository", "StoredEnergyReading"]
