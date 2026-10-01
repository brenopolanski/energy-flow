"""Port for enqueueing background processing of a stored reading."""

from typing import Protocol
from uuid import UUID


class ReadingJobDispatcher(Protocol):
    """Schedules processing for a reading that has already been stored."""

    async def dispatch(self, reading_id: UUID) -> None:
        """Enqueue processing for ``reading_id``."""
