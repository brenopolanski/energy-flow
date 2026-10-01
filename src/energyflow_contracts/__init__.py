"""Shared contracts for EnergyFlow services.

Services may depend on these models and names. They do not share
application or domain logic through this package.
"""

from energyflow_contracts.events import PROCESS_READING_TASK, TASK_QUEUE, ReadingAccepted
from energyflow_contracts.readings import EnergyReading, SensorId

__all__ = [
    "PROCESS_READING_TASK",
    "TASK_QUEUE",
    "EnergyReading",
    "ReadingAccepted",
    "SensorId",
]
