"""Prometheus metrics for HTTP calls, publishes, tasks, and result reads."""

import os

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

HTTP_REQUESTS = Counter(
    "energyflow_http_requests_total",
    "HTTP responses, excluding health and metrics scrapes.",
    ["service", "method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "energyflow_http_request_duration_seconds",
    "HTTP request latency, excluding health and metrics scrapes.",
    ["service", "method", "path"],
    buckets=_BUCKETS,
)
READINGS_PUBLISHED = Counter(
    "energyflow_readings_published_total",
    "Accepted readings published to the task queue.",
)
TASKS = Counter(
    "energyflow_tasks_total",
    "Processing task outcomes.",
    ["outcome"],
)
TASK_DURATION = Histogram(
    "energyflow_task_duration_seconds",
    "Time spent inside one processing task.",
    buckets=_BUCKETS,
)
RESULT_LOOKUPS = Counter(
    "energyflow_result_lookups_total",
    "Result lookups by reading id.",
    ["outcome"],
)


def render_metrics() -> bytes:
    """Render the current process, or every worker process when asked."""
    metrics_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if metrics_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest()
