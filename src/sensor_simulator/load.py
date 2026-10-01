"""Build readings for many sensors and post them at a chosen concurrency."""

import asyncio
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def sensor_id(index: int) -> str:
    """Stable id for sensor number ``index``, starting at 1."""
    return f"sensor-{index:05d}"


def reading_power(sensor_index: int, sequence: int) -> float:
    """Deterministic non-negative power for one reading."""
    return float(200 + ((sensor_index * 37 + sequence * 13) % 5800))


def planned_readings(
    sensors: int,
    readings_per_sensor: int,
    *,
    start: datetime | None = None,
) -> list[dict[str, object]]:
    """One JSON body per reading, in sensor order."""
    if sensors < 1:
        raise ValueError("sensors must be at least 1")
    if readings_per_sensor < 1:
        raise ValueError("readings_per_sensor must be at least 1")
    origin = start or datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc)
    bodies: list[dict[str, object]] = []
    for sensor_index in range(1, sensors + 1):
        for sequence in range(readings_per_sensor):
            moment = origin + timedelta(seconds=sequence)
            bodies.append(
                {
                    "sensor_id": sensor_id(sensor_index),
                    "timestamp": moment.isoformat().replace("+00:00", "Z"),
                    "power_watts": reading_power(sensor_index, sequence),
                }
            )
    return bodies


@dataclass(frozen=True)
class CallResult:
    status: int
    seconds: float
    body: str


@dataclass(frozen=True)
class LoadReport:
    sensors: int
    submitted: int
    statuses: dict[int, int]
    latency_seconds: list[float]
    sample_reading_id: str | None

    @property
    def accepted(self) -> int:
        return self.statuses.get(202, 0)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def _request(method: str, url: str, payload: dict[str, object] | None, timeout: float) -> CallResult:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"content-type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            return CallResult(response.status, time.perf_counter() - started, body)
    except urllib.error.HTTPError as exc:
        return CallResult(exc.code, time.perf_counter() - started, exc.read().decode())
    except urllib.error.URLError as exc:
        return CallResult(0, time.perf_counter() - started, str(exc.reason))


async def run_load(
    url: str,
    sensors: int,
    readings_per_sensor: int,
    concurrency: int,
    timeout: float = 30,
) -> LoadReport:
    """POST every planned reading to ``url`` and collect status and latency."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    bodies = planned_readings(sensors, readings_per_sensor)
    endpoint = url.rstrip("/") + "/readings"
    gate = asyncio.Semaphore(concurrency)

    async def post(body: dict[str, object]) -> CallResult:
        async with gate:
            return await asyncio.to_thread(_request, "POST", endpoint, body, timeout)

    results = await asyncio.gather(*(post(body) for body in bodies))
    statuses: dict[int, int] = {}
    sample_reading_id = None
    for result in results:
        statuses[result.status] = statuses.get(result.status, 0) + 1
        if sample_reading_id is None and result.status == 202:
            sample_reading_id = json.loads(result.body)["id"]
    return LoadReport(
        sensors=sensors,
        submitted=len(results),
        statuses=statuses,
        latency_seconds=[result.seconds for result in results],
        sample_reading_id=sample_reading_id,
    )


async def wait_for_result(
    results_url: str,
    reading_id: str,
    timeout: float = 60,
) -> CallResult | None:
    """Poll results until the reading is stored, or the timeout passes."""
    endpoint = results_url.rstrip("/") + f"/results/{reading_id}"
    deadline = time.monotonic() + timeout
    last: CallResult | None = None
    while time.monotonic() < deadline:
        last = await asyncio.to_thread(_request, "GET", endpoint, None, 10)
        if last.status == 200:
            return last
        await asyncio.sleep(0.5)
    return last


def format_report(report: LoadReport) -> str:
    statuses = ", ".join(
        f"{status}={count}" for status, count in sorted(report.statuses.items())
    )
    lines = [
        f"sensors {report.sensors}",
        f"submitted {report.submitted}",
        f"statuses {statuses}",
        (
            "latency_seconds "
            f"p50={percentile(report.latency_seconds, 50):.4f} "
            f"p95={percentile(report.latency_seconds, 95):.4f} "
            f"max={max(report.latency_seconds, default=0):.4f}"
        ),
    ]
    if report.sample_reading_id is not None:
        lines.append(f"sample_reading_id {report.sample_reading_id}")
    return "\n".join(lines)
