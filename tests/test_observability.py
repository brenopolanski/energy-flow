import json
import logging

from energyflow_observability.http import route_label
from energyflow_observability.logging import JsonFormatter


def test_route_label_collapses_result_ids() -> None:
    assert route_label("/results/98cc0f71-3296-44b5-a082-e87c1ed5357e") == "/results/{reading_id}"
    assert route_label("/readings") == "/readings"


def test_json_formatter_keeps_the_request_id() -> None:
    formatter = JsonFormatter("ingestion")
    record = logging.LogRecord(
        name="ingestion_service.app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="published reading",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-123"
    record.reading_id = "98cc0f71-3296-44b5-a082-e87c1ed5357e"
    record.correlation_id = "req-123"

    payload = json.loads(formatter.format(record))

    assert payload["service"] == "ingestion"
    assert payload["message"] == "published reading"
    assert payload["request_id"] == "req-123"
    assert payload["correlation_id"] == "req-123"
    assert payload["reading_id"] == "98cc0f71-3296-44b5-a082-e87c1ed5357e"
