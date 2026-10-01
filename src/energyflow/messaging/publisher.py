"""Publisher contract for accepted energy readings."""

from typing import Protocol

from energyflow.models import EnergyReading


class ReadingEventPublisher(Protocol):
    """Publishes an event when a reading is accepted."""

    async def publish_reading_accepted(self, reading: EnergyReading) -> None:
        """Publish one event for ``reading``."""
