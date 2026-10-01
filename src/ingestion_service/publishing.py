"""How ingestion publishes an accepted reading."""

import asyncio
import os
from typing import Protocol

from celery import Celery

from energyflow_contracts.events import PROCESS_READING_TASK, TASK_QUEUE, ReadingAccepted

DEFAULT_BROKER_URL = "amqp://guest:guest@127.0.0.1/"


def broker_url() -> str:
    return os.environ.get("ENERGYFLOW_RABBITMQ_URL", DEFAULT_BROKER_URL)


celery_app = Celery("energyflow.ingestion", broker=broker_url())
celery_app.conf.task_default_queue = TASK_QUEUE


class ReadingAcceptedPublisher(Protocol):
    """Publishes one accepted reading. The API does not import the worker."""

    async def publish(self, event: ReadingAccepted) -> None:
        """Publish ``event`` for the processing service."""


class CeleryReadingAcceptedPublisher:
    """Sends ``ReadingAccepted`` as a Celery task message."""

    def __init__(self, app: Celery | None = None) -> None:
        self._app = app or celery_app

    async def publish(self, event: ReadingAccepted) -> None:
        await asyncio.to_thread(
            self._app.send_task,
            PROCESS_READING_TASK,
            args=[event.to_message()],
            queue=TASK_QUEUE,
        )
