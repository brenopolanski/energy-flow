"""Post readings for many sensors.

    python -m sensor_simulator --sensors 100 --concurrency 20
    python -m sensor_simulator --sensors 10000 --concurrency 50 --results-url http://127.0.0.1:8003
"""

import argparse
import asyncio
import sys

from sensor_simulator.load import format_report, run_load, wait_for_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post simulated sensor readings to ingestion.")
    parser.add_argument("--url", default="http://127.0.0.1:8001", help="Ingestion base URL")
    parser.add_argument("--results-url", default=None, help="Results base URL, polled for one accepted id")
    parser.add_argument("--sensors", type=int, default=10)
    parser.add_argument("--readings-per-sensor", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--result-timeout", type=float, default=60)
    args = parser.parse_args(argv)

    report = asyncio.run(
        run_load(
            args.url,
            args.sensors,
            args.readings_per_sensor,
            args.concurrency,
            args.timeout,
        )
    )
    print(format_report(report))
    if report.accepted != report.submitted:
        return 1
    if args.results_url and report.sample_reading_id:
        found = asyncio.run(
            wait_for_result(args.results_url, report.sample_reading_id, args.result_timeout)
        )
        if found is None or found.status != 200:
            status = 0 if found is None else found.status
            print(f"result {status} reading_id={report.sample_reading_id}")
            return 1
        print(f"result {found.status} {found.body}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
