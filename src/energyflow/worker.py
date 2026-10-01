"""Celery worker for accepted energy readings.

RabbitMQ is the broker. Tasks go to the ``energyflow.tasks`` queue, which is
separate from the ``energy_readings`` queue used by the stage 7 consumer.

    celery -A energyflow.worker:celery_app worker --loglevel=info
"""

import asyncio
import logging
import os
from uuid import UUID

import asyncpg
from celery import Celery
from celery.app import trace as celery_trace
from celery.signals import worker_process_init

from energyflow.disaggregation import EnergyDisaggregationService
from energyflow.messaging.rabbitmq import DEFAULT_URL
from energyflow.persistence.postgres import (
    DEFAULT_DATABASE_URL,
    PostgresDisaggregationResultRepository,
    PostgresEnergyReadingRepository,
    connect,
)
from energyflow.persistence.results import StoredDisaggregation
from energyflow.processing import (
    InvalidTaskArgumentError,
    PermanentProcessingError,
    process_stored_reading,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_RETRY_SECONDS = 2
MAX_RETRY_SECONDS = 60
TASK_QUEUE = "energyflow.tasks"

# PostgreSQL states for a conflict, a shutdown, or a dead connection.
# 23514 (check_violation) is intentionally absent: that row will not change.
_RETRYABLE_SQLSTATE = frozenset(
    {
        "40001",
        "40P01",
        "08000",
        "08001",
        "08003",
        "08006",
        "53300",
        "57P01",
        "57P02",
        "57P03",
    }
)

_CONNECTION_ERRORS = (
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
    asyncpg.CannotConnectNowError,
    asyncpg.TooManyConnectionsError,
    asyncpg.ConnectionDoesNotExistError,
)


def broker_url() -> str:
    return os.environ.get("ENERGYFLOW_RABBITMQ_URL", DEFAULT_URL)


def database_url() -> str:
    return os.environ.get("ENERGYFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)


celery_app = Celery("energyflow", broker=broker_url())
celery_app.conf.update(
    task_default_queue=TASK_QUEUE,
    task_default_exchange=TASK_QUEUE,
    task_default_routing_key=TASK_QUEUE,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    # RabbitMQ 4 rejects a transient queue that is not exclusive. Celery's
    # control mailbox is that kind of queue unless this is enabled.
    control_queue_exclusive=True,
    event_queue_exclusive=True,
)


@worker_process_init.connect
def _prepare_spawned_worker(**_kwargs: object) -> None:
    """Prepare Celery's fast-trace cache inside each pool process.

    Celery 5.6 starts pool processes with spawn on macOS. A spawned child
    does not inherit the cache or the task tracers the parent built, so the
    task crashes before our code runs. Rebuilding them here is the same
    setup the parent already did.
    """
    from celery.app.trace import build_tracer

    celery_trace.setup_worker_optimizations(celery_app)
    hostname = celery_trace.gethostname()
    for name, task in celery_app.tasks.items():
        task.__trace__ = build_tracer(
            name,
            task,
            celery_app.loader,
            hostname,
            app=celery_app,
        )


def retry_countdown(retries: int) -> int:
    """Seconds to wait before retry number ``retries``.

    The first retry waits 2 seconds, then 4, 8, 16, and 32. The wait never
    grows past 60 seconds.
    """
    exponent = max(retries, 0)
    return min(MAX_RETRY_SECONDS, BASE_RETRY_SECONDS * (2**exponent))


def is_retryable(exc: BaseException) -> bool:
    """True when another attempt might succeed."""
    if isinstance(exc, PermanentProcessingError):
        return False
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, _CONNECTION_ERRORS):
        return True
    return getattr(exc, "sqlstate", None) in _RETRYABLE_SQLSTATE


def classify_failure(
    exc: BaseException,
    retries: int,
    max_retries: int,
) -> tuple[str, int | None]:
    """Choose ``retry`` with a countdown, or ``fail`` with no countdown."""
    if is_retryable(exc) and retries < max_retries:
        return "retry", retry_countdown(retries)
    return "fail", None


def run_reading_task(reading_id: str) -> StoredDisaggregation:
    """Run one attempt. Opens a database pool for this call and closes it."""
    try:
        parsed = UUID(reading_id)
    except ValueError as exc:
        raise InvalidTaskArgumentError(
            f"reading id {reading_id!r} is not a UUID"
        ) from exc
    return asyncio.run(_process_once(parsed))


async def _process_once(reading_id: UUID) -> StoredDisaggregation:
    pool = await connect(database_url())
    try:
        return await process_stored_reading(
            reading_id,
            readings=PostgresEnergyReadingRepository(pool),
            results=PostgresDisaggregationResultRepository(pool),
            service=EnergyDisaggregationService(),
        )
    finally:
        await pool.close()


@celery_app.task(
    bind=True,
    name="energyflow.process_energy_reading",
    max_retries=MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_energy_reading(self, reading_id: str) -> str:
    """Load one stored reading, disaggregate it, and persist the split."""
    try:
        result = run_reading_task(reading_id)
    except Exception as exc:
        action, countdown = classify_failure(
            exc,
            self.request.retries,
            self.max_retries,
        )
        if action == "retry":
            logger.warning(
                "Retrying reading %s after %s in %ss (retry %s of %s)",
                reading_id,
                type(exc).__name__,
                countdown,
                self.request.retries + 1,
                self.max_retries,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        logger.error("Reading %s failed permanently: %s", reading_id, exc)
        raise
    return str(result.reading_id)


class CeleryReadingJobDispatcher:
    """Enqueues ``process_energy_reading`` through the Celery broker."""

    async def dispatch(self, reading_id: UUID) -> None:
        await asyncio.to_thread(process_energy_reading.delay, str(reading_id))
