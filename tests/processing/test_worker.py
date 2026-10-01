import pytest
from fastapi.testclient import TestClient

from energyflow_contracts.events import PROCESS_READING_TASK, TASK_QUEUE
from processing_service.health import create_app
from processing_service.use_case import InvalidReadingError
from processing_service.worker import (
    MAX_RETRIES,
    celery_app,
    classify_failure,
    process_reading_accepted,
    retry_countdown,
    run_reading_task,
)


class _SqlstateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def test_health() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_permanent_failures_are_not_retried() -> None:
    assert classify_failure(InvalidReadingError("bad"), 0, MAX_RETRIES) == ("fail", None)
    assert classify_failure(RuntimeError("bug"), 0, MAX_RETRIES) == ("fail", None)
    assert classify_failure(_SqlstateError("23514"), 0, MAX_RETRIES) == ("fail", None)


def test_invalid_payload_fails_before_opening_the_database() -> None:
    with pytest.raises(InvalidReadingError):
        run_reading_task({"reading_id": "not-a-uuid"})


def test_celery_broker_is_rabbitmq_and_uses_the_contract_queue() -> None:
    assert celery_app.conf.broker_url.startswith("amqp://")
    assert celery_app.conf.task_default_queue == TASK_QUEUE
    assert celery_app.conf.control_queue_exclusive is True
    assert process_reading_accepted.name == PROCESS_READING_TASK
    assert process_reading_accepted.max_retries == MAX_RETRIES
    assert celery_app.tasks[PROCESS_READING_TASK] is not None
