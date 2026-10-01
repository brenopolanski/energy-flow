"""JSON logs on stdout, one object per line."""

import json
import logging
from datetime import datetime, timezone

from energyflow_observability.context import current_request_id

_FIELDS = (
    "correlation_id",
    "reading_id",
    "sensor_id",
    "outcome",
    "method",
    "path",
    "status",
    "duration_seconds",
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None) or current_request_id()
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if request_id:
            payload["request_id"] = request_id
        for key in _FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service: str) -> None:
    """Attach one JSON handler to the root logger."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    setattr(handler, "_energyflow", True)
    root.handlers = [
        existing
        for existing in root.handlers
        if not getattr(existing, "_energyflow", False)
    ]
    root.addHandler(handler)
