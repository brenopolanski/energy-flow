import pytest

from energyflow.messaging.rabbitmq import DEFAULT_QUEUE
from energyflow.processing import InvalidTaskArgumentError, ReadingNotFoundError
from energyflow.worker import (
    MAX_RETRIES,
    TASK_QUEUE,
    celery_app,
    classify_failure,
    process_energy_reading,
    retry_countdown,
    run_reading_task,
)


class _SqlstateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def test_retry_countdown_grows_exponentially_and_caps() -> None:
    assert [retry_countdown(attempt) for attempt in range(6)] == [2, 4, 8, 16, 32, 60]


def test_transient_failures_retry_until_the_limit() -> None:
    assert classify_failure(TimeoutError("down"), retries=0, max_retries=5) == ("retry", 2)
    assert classify_failure(ConnectionError("reset"), retries=1, max_retries=5) == (
        "retry",
        4,
    )
    assert classify_failure(_SqlstateError("40001"), retries=2, max_retries=5) == (
        "retry",
        8,
    )
    assert classify_failure(TimeoutError("down"), retries=5, max_retries=5) == ("fail", None)


def test_permanent_and_logical_failures_are_not_retried() -> None:
    assert classify_failure(ReadingNotFoundError("missing"), 0, MAX_RETRIES) == ("fail", None)
    assert classify_failure(InvalidTaskArgumentError("bad"), 0, MAX_RETRIES) == ("fail", None)
    assert classify_failure(RuntimeError("bug"), 0, MAX_RETRIES) == ("fail", None)
    assert classify_failure(_SqlstateError("23514"), 0, MAX_RETRIES) == ("fail", None)


def test_invalid_task_argument_fails_before_opening_the_database() -> None:
    with pytest.raises(InvalidTaskArgumentError):
        run_reading_task("not-a-uuid")


def test_celery_broker_is_rabbitmq_and_uses_its_own_queue() -> None:
    assert celery_app.conf.broker_url.startswith("amqp://")
    assert celery_app.conf.task_default_queue == TASK_QUEUE
    assert celery_app.conf.control_queue_exclusive is True
    assert TASK_QUEUE != DEFAULT_QUEUE
    assert process_energy_reading.name == "energyflow.process_energy_reading"
    assert process_energy_reading.max_retries == MAX_RETRIES
    assert celery_app.tasks["energyflow.process_energy_reading"] is not None
