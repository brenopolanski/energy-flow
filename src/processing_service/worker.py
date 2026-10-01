"""Celery worker for accepted readings.

RabbitMQ is the broker. Tasks arrive on ``energyflow.tasks`` under the name
``energyflow.readings.process``.

    celery -A processing_service.worker:celery_app worker --loglevel=info
"""

import asyncio
import logging
import os
import time

import asyncpg
from celery import Celery
from celery.app import trace as celery_trace
from celery.signals import setup_logging, worker_process_init, worker_ready
from pydantic import ValidationError

from energyflow_observability.http import serve_worker_endpoints
from energyflow_observability.logging import configure_logging
from energyflow_observability.metrics import TASK_DURATION, TASKS

from energyflow_contracts.events import PROCESS_READING_TASK, TASK_QUEUE, ReadingAccepted
from processing_service.domain import EnergyDisaggregationService
from processing_service.persistence.postgres import (
    DEFAULT_DATABASE_URL,
    PostgresDisaggregationResultRepository,
    PostgresEnergyReadingRepository,
    connect,
)
from processing_service.persistence.results import StoredDisaggregation
from processing_service.use_case import (
    InvalidReadingError,
    PermanentProcessingError,
    process_accepted_reading,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_RETRY_SECONDS = 2
MAX_RETRY_SECONDS = 60
DEFAULT_BROKER_URL = "amqp://guest:guest@127.0.0.1/"

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
    return os.environ.get("ENERGYFLOW_RABBITMQ_URL", DEFAULT_BROKER_URL)


def database_url() -> str:
    return os.environ.get("ENERGYFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)


celery_app = Celery("energyflow.processing", broker=broker_url())
celery_app.conf.update(
    task_default_queue=TASK_QUEUE,
    task_default_exchange=TASK_QUEUE,
    task_default_routing_key=TASK_QUEUE,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    # RabbitMQ 4 rejects a transient queue that is not exclusive. Celery's
    # control mailbox is that kind of queue unless this is enabled.
    control_queue_exclusive=True,
    event_queue_exclusive=True,
)


@setup_logging.connect
def _configure_worker_logging(**_kwargs: object) -> None:
    configure_logging("processing")


@worker_ready.connect
def _on_worker_ready(**_kwargs: object) -> None:
    """Create the tables, then expose /health and /metrics."""
    asyncio.run(_prepare_database())
    serve_worker_endpoints()
    logger.info("processing worker ready")


async def _prepare_database() -> None:
    pool = await connect(database_url())
    await pool.close()


@worker_process_init.connect
def _prepare_spawned_worker(**_kwargs: object) -> None:
    """Prepare Celery's fast-trace cache inside each pool process.

    Celery 5.6 starts pool processes with spawn on macOS. A spawned child
    does not inherit the cache or the task tracers the parent built, so the
    task crashes before our code runs.
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
    """Seconds to wait before retry number ``retries``."""
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


def run_reading_task(payload: dict[str, object]) -> StoredDisaggregation:
    """Run one attempt. Opens a database pool for this call and closes it."""
    try:
        event = ReadingAccepted.from_message(payload)
    except ValidationError as exc:
        raise InvalidReadingError("accepted reading payload is invalid") from exc
    return asyncio.run(_process_once(event))


async def _process_once(event: ReadingAccepted) -> StoredDisaggregation:
    pool = await connect(database_url())
    try:
        return await process_accepted_reading(
            event,
            readings=PostgresEnergyReadingRepository(pool),
            results=PostgresDisaggregationResultRepository(pool),
            service=EnergyDisaggregationService(),
        )
    finally:
        await pool.close()


@celery_app.task(
    bind=True,
    name=PROCESS_READING_TASK,
    max_retries=MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_reading_accepted(self, payload: dict[str, object]) -> str:
    """Disaggregate one accepted reading and store the split."""
    started = time.perf_counter()
    outcome = "failure"
    reading_id = _reading_label(payload)
    correlation_id = _correlation_id(payload)
    try:
        result = run_reading_task(payload)
        outcome = "success"
        logger.info(
            "processed reading",
            extra={
                "reading_id": reading_id,
                "correlation_id": correlation_id,
                "outcome": outcome,
            },
        )
        return str(result.reading_id)
    except Exception as exc:
        action, countdown = classify_failure(
            exc,
            self.request.retries,
            self.max_retries,
        )
        if action == "retry":
            outcome = "retry"
            logger.warning(
                "retrying reading",
                extra={
                    "reading_id": reading_id,
                    "correlation_id": correlation_id,
                    "outcome": outcome,
                },
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        logger.error(
            "reading failed permanently",
            extra={
                "reading_id": reading_id,
                "correlation_id": correlation_id,
                "outcome": "failure",
            },
        )
        raise
    finally:
        TASKS.labels(outcome=outcome).inc()
        TASK_DURATION.observe(time.perf_counter() - started)


def _reading_label(payload: dict[str, object]) -> str:
    reading_id = payload.get("reading_id")
    return str(reading_id) if reading_id is not None else "<missing id>"


def _correlation_id(payload: dict[str, object]) -> str | None:
    value = payload.get("correlation_id")
    if isinstance(value, str) and value:
        return value
    return None
