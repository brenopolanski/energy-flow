# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

Stage 9 splits the system into three services. They do not import each other's application code. The shared package `energyflow_contracts` holds the reading model and the `ReadingAccepted` event.

```text
sensor
  ↓ HTTP
ingestion-service          FastAPI :8001
  validate EnergyReading
  publish ReadingAccepted
  ↓
RabbitMQ                   queue energyflow.tasks
  task energyflow.readings.process
  ↓
processing-service         Celery worker
  disaggregate
  store energy_readings
  store disaggregation_results
  ↓
PostgreSQL
  ↑
results-service            FastAPI :8003
  GET /results/{reading_id}
```

Ingestion does not store the split and does not run disaggregation. Processing does not accept HTTP readings. Results does not publish events. Processing and results share one PostgreSQL database: processing writes, results reads. That is a schema coupling, chosen instead of a second database.

Local infrastructure is Docker Compose. Kubernetes is not used: Compose already runs each process, the broker, and the database, which is enough to see latency, queue depth, and a slow worker.

## Requirements

- Python 3.12 or newer
- PostgreSQL for stored results
- RabbitMQ for the Celery broker

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Tests

Unit tests do not need PostgreSQL or RabbitMQ:

```bash
pytest -m "not integration and not rabbitmq"
```

PostgreSQL integration tests use `ENERGYFLOW_DATABASE_URL`. The default is `postgresql:///energyflow_test`.

```bash
pytest -m integration
```

## Run

Broker URL: `ENERGYFLOW_RABBITMQ_URL` (default `amqp://guest:guest@127.0.0.1/`).

Database URL: `ENERGYFLOW_DATABASE_URL` (default `postgresql:///energyflow_test`).

```bash
uvicorn ingestion_service.app:app --port 8001
uvicorn processing_service.health:app --port 8002
uvicorn results_service.app:app --port 8003
celery -A processing_service.worker:celery_app worker --loglevel=info
```

- `GET /health` on each HTTP process
- `POST /readings` on ingestion returns `202 Accepted` with the reading id
- `GET /results/{reading_id}` on the results service returns the stored split, or `404` when it is not stored yet

The worker retries connection, deadlock, and shutdown failures up to 5 times, waiting 2, 4, 8, 16, then 32 seconds. An invalid event is not retried. A repeated event for the same reading id keeps the first stored split.

## Docker Compose

Compose creates one network. Service names are the hostnames on that network.

```text
ingestion-service  --amqp-->  rabbitmq:5672
processing-service --amqp-->  rabbitmq:5672
processing-service --sql-->   postgres:5432
results-service    --sql-->   postgres:5432
```

From your machine the published ports are:

| Process                   | URL                                                                   |
| ------------------------- | --------------------------------------------------------------------- |
| Ingestion                 | http://127.0.0.1:8001                                                 |
| Results                   | http://127.0.0.1:8003                                                 |
| Worker health and metrics | http://127.0.0.1:9100                                                 |
| RabbitMQ management       | http://127.0.0.1:15672 (`energyflow` / `energyflow`)                  |
| PostgreSQL                | `127.0.0.1:5433` (`energyflow` / `energyflow`, database `energyflow`) |

PostgreSQL is published on 5433 so it does not collide with a database already listening on 5432. Inside the network the host is still `postgres` and the port is 5432.

The broker user is `energyflow`, not `guest`. RabbitMQ refuses the `guest` user from another container.

```bash
docker compose up --build
```

`processing-service` is the Celery worker. On startup it creates the tables, then serves `GET /health` and `GET /metrics` on port 9100. `GET /health` on 8002 is only for the separate health process in the manual run above. Compose does not start that process.

Ingestion and results answer `GET /health`. Postgres uses `pg_isready`. RabbitMQ uses `rabbitmq-diagnostics ping`. Results starts after the worker is healthy, so the tables exist before the first read.

Shut the stack down with:

```bash
docker compose down
```

`docker compose down -v` also deletes the PostgreSQL volume.

## Logs, request ids, and metrics

Each HTTP call gets an `X-Request-ID`. Ingestion copies that id onto `ReadingAccepted.correlation_id`. The worker logs the same id with the `reading_id`. A later `GET /results/{reading_id}` is a new HTTP call, so it has its own request id. The `reading_id` is what ties the three steps together.

Logs are one JSON object per line on stdout:

```bash
docker compose logs ingestion-service
docker compose logs processing-service
docker compose logs results-service
```

`GET /metrics` is Prometheus text.

- `energyflow_http_request_duration_seconds` — API latency for `/readings` and `/results/{reading_id}`. Health checks are not included.
- `energyflow_readings_published_total` — readings accepted onto the queue.
- `energyflow_tasks_total{outcome="success|retry|failure"}` — task processing and failures. The worker metric is on port 9100.
- `energyflow_task_duration_seconds` — time inside one task, including the database writes.
- `energyflow_result_lookups_total{outcome="hit|miss"}` — stored rows versus 404.

## What to watch

API latency:

```bash
curl -s http://127.0.0.1:8001/metrics | grep energyflow_http_request_duration_seconds
curl -s http://127.0.0.1:8003/metrics | grep energyflow_http_request_duration_seconds
```

The simulator also prints p50, p95, and max for the POSTs it sent.

Queue depth:

```bash
docker compose exec rabbitmq rabbitmqctl list_queues name messages messages_ready messages_unacknowledged
```

`energyflow.tasks` is the reading queue. `messages_ready` are waiting. `messages_unacknowledged` are checked out by a worker and not acked yet. The management UI shows the same numbers.

Task processing and failures:

```bash
curl -s http://127.0.0.1:9100/metrics | grep energyflow_tasks_total
docker compose logs processing-service
```

`outcome` is `success`, `retry`, or `failure`. A retryable database error waits 2, 4, 8, 16, then 32 seconds. An invalid payload is `failure` and is not retried.

Database usage:

```bash
docker compose exec postgres psql -U energyflow -d energyflow -c \
  "SELECT count(*) AS readings FROM energy_readings;"
docker compose exec postgres psql -U energyflow -d energyflow -c \
  "SELECT count(*) AS results FROM disaggregation_results;"
docker compose exec postgres psql -U energyflow -d energyflow -c \
  "SELECT state, count(*) FROM pg_stat_activity WHERE datname = 'energyflow' GROUP BY state;"
```

A `202` from ingestion means the event was published. It does not mean the row exists yet. `GET /results/{id}` stays `404` until the worker commits both rows.

## Sensor simulator

The simulator posts to ingestion. It does not write to PostgreSQL itself.

```bash
python -m sensor_simulator --sensors 20 --concurrency 5 \
  --results-url http://127.0.0.1:8003
```

`--sensors` is how many sensor ids to generate (`sensor-00001` onward). `--readings-per-sensor` repeats each sensor. `--concurrency` is how many POSTs run at once.

Load-test scenario, 100 sensors:

```bash
python -m sensor_simulator --sensors 100 --readings-per-sensor 1 --concurrency 20 \
  --results-url http://127.0.0.1:8003
```

Heavier scenario, 10,000 sensors, one reading each:

```bash
python -m sensor_simulator --sensors 10000 --readings-per-sensor 1 --concurrency 50 \
  --results-url http://127.0.0.1:8003
```

While it runs, watch `energyflow.tasks` and `energyflow_tasks_total`. The POST can return `202` before `GET /results/{id}` returns `200`. That gap is the asynchronous processing.

## Scaling

One hundred readings is a short queue. One worker inserts them and the depth returns to zero. Latency is mostly the HTTP call plus one publish.

Ten thousand readings changes the shape of the system:

- Ingestion is one process. Each request validates the body and publishes one Celery message. The ceiling is that process and the broker, not the bitmask.
- The worker opens a PostgreSQL pool of one or two connections, applies the schema, inserts two rows, and closes the pool on every task. That connection work dominates the disaggregation, which only tries eight appliance combinations. Compose starts the worker with `--concurrency=4`, so about four tasks run at once.
- If ingestion publishes faster than the worker finishes, `messages_ready` grows. The queue is the buffer. Unacked messages stay with the worker until the task finishes or the worker is lost.
- PostgreSQL insert rate and connection count are the shared ceiling. Processing and results use the same database.
- A result read is a primary-key lookup. Extra results processes do not speed up a run that is waiting on writes.

What adds capacity: more ingestion processes behind the same broker, and more processing workers consuming `energyflow.tasks`. Raise `--concurrency` only while PostgreSQL `max_connections` stays above the workers plus the results pool. A pool of ten connections per task will hit that limit at a hundred sensors. What does not change the ceiling: splitting the disaggregation bitmask across more CPUs, or adding a cluster scheduler. The slow part is the database work per message and the single queue.
