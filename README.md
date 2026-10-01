# EnergyFlow

EnergyFlow accepts instantaneous power readings, estimates which appliances produced that power, and stores the result for later lookup.

The work is split across three services. Ingestion validates a reading and publishes it. A Celery worker consumes the message, runs the estimate, and writes PostgreSQL. A separate API reads the stored result. RabbitMQ sits between the HTTP accept and the background job, so the client receives a response before processing finishes.

The stack is Python, FastAPI, Pydantic, Celery, RabbitMQ, PostgreSQL, and Docker Compose. Together they show asynchronous processing, event-driven communication, service boundaries, retries, idempotency, observability, connection pooling, and eventual consistency.

## Architecture

```mermaid
flowchart LR
    Client[Sensor / Client]
    Ingestion[Ingestion Service<br/>FastAPI :8001]
    Broker[(RabbitMQ<br/>queue energyflow.tasks)]
    Worker[Processing Service<br/>Celery worker]
    Database[(PostgreSQL<br/>database energyflow)]
    Results[Results Service<br/>FastAPI :8003]

    Client -->|POST /readings| Ingestion
    Ingestion -->|task energyflow.readings.process| Broker
    Broker -->|deliver task| Worker
    Worker -->|write readings and results| Database
    Client -->|GET /results/id| Results
    Results -->|read join| Database
```

| Service | Responsibility |
| --- | --- |
| Ingestion | Validate the HTTP body, assign a reading id, publish one Celery task. |
| RabbitMQ | Hold `energyflow.tasks` until a worker takes the message. |
| Processing | Run disaggregation and insert both tables. |
| PostgreSQL | Store the reading and the appliance split. |
| Results | Return the stored split for one reading id. |

Ingestion does not write to PostgreSQL and does not disaggregate. Processing does not accept sensor HTTP calls. Results does not publish. Processing and results share one database: processing creates and writes the tables, results only reads them.

The sensor simulator is a client. It posts to ingestion. It does not write SQL.

## Request Flow

```text
Client
  → Ingestion Service
  → Pydantic validation
  → RabbitMQ
  → Celery worker
  → Disaggregation
  → PostgreSQL
  → Results Service
```

```mermaid
sequenceDiagram
    participant C as Client
    participant I as Ingestion :8001
    participant Q as RabbitMQ
    participant W as Celery worker
    participant DB as PostgreSQL
    participant R as Results :8003

    C->>I: POST /readings
    I->>I: Validate EnergyReading
    I->>Q: send_task energyflow.readings.process
    I-->>C: 202 Accepted with reading id

    Q->>W: Deliver ReadingAccepted
    W->>W: Disaggregate
    W->>DB: Insert energy_readings and disaggregation_results

    C->>R: GET /results/{reading_id}
    R->>DB: Join on reading id
    DB-->>R: Row or no row
    R-->>C: 200 OK or 404
```

Validation of the HTTP body is synchronous. Publishing is synchronous from the client's point of view: the handler waits until `send_task` returns, then responds. Disaggregation and the inserts happen later, on the worker. That is why `POST /readings` can return while `GET /results/{id}` still has nothing to read.

`send_task` itself is a blocking Celery call. The ingestion handler runs it in a worker thread so it does not stall the FastAPI event loop.

## Asynchronous Processing

`200 OK` would mean the requested work is finished and the body is the result. `202 Accepted` means the reading was validated and the task was published. The response contains the new id, the sensor, the timestamp, the measured watts, and `"status": "accepted"`. It does not contain the appliance split.

```text
POST /readings
      ↓
202 Accepted
      ↓
RabbitMQ  energyflow.tasks
      ↓
Celery worker
      ↓
PostgreSQL
      ↓
GET /results/{reading_id}
      ↓
200 OK
```

Until the worker commits both rows, the same `GET` returns `404`. The results service has no "pending" status. A missing row and an unknown id produce the same response. An id that is not a UUID is rejected earlier, with `422`, by request parsing.

A client that needs the split polls `GET /results/{reading_id}`, or follows the logs and metrics until the task succeeds.

## Technology Stack

| Component | Technology | Purpose |
| --- | --- | --- |
| Language | Python 3.12+ | Application code |
| HTTP | FastAPI, Uvicorn | Ingestion and results APIs |
| Validation | Pydantic v2 | Reading and event models |
| Background jobs | Celery | Consume `energyflow.readings.process` |
| Broker | RabbitMQ 4 | Queue `energyflow.tasks` |
| Database | PostgreSQL 16 | Readings and disaggregation rows |
| Database driver | asyncpg | Async pools and queries |
| Metrics | prometheus-client | Text exposition on `/metrics` |
| Containers | Docker Compose | Local orchestration |
| Tests | pytest, pytest-asyncio | Unit and PostgreSQL integration tests |

There is no Prometheus server, Grafana, Redis, Kafka, or Kubernetes in this repository. Metrics are scraped by requesting `/metrics` directly.

## Services

### Ingestion Service

FastAPI application `ingestion_service.app:app`, published on port **8001**.

`POST /readings` accepts an `EnergyReading`:

- `sensor_id`: 1–64 characters, starting with a letter or digit, then letters, digits, `_`, or `-`
- `timestamp`: timezone-aware
- `power_watts`: greater than or equal to zero

Unknown JSON fields are rejected. A negative power returns `422` and nothing is published.

On success the service generates a UUID, copies the current `X-Request-ID` onto the event as `correlation_id`, and publishes the full reading. It does not disaggregate, and it does not insert a row. If publish raises, the client does not receive `202`.

`GET /health` returns `{"status":"ok"}`. It does not check RabbitMQ.

`GET /metrics` returns Prometheus text for this process.

### Processing Service

Celery application `processing_service.worker:celery_app`. The Compose command is:

```text
celery -A processing_service.worker:celery_app worker --loglevel=info --concurrency=4
```

The task name is `energyflow.readings.process`. The queue, exchange, and routing key are all `energyflow.tasks`. The payload is the `ReadingAccepted` JSON, including `reading_id`, sensor, timestamp, watts, and `correlation_id`.

The worker validates the payload again. It disaggregates only when that reading id has no stored result yet. It then inserts `energy_readings` and `disaggregation_results`. Each attempt opens a PostgreSQL pool, applies the schema, and closes the pool when the attempt finishes.

On startup the worker applies the schema once, then serves `GET /health` and `GET /metrics` on port **9100**. That health response means the process reached ready after the schema step. It does not re-check the database or the broker on later health requests.

A second, smaller app, `processing_service.health:app`, only exposes `GET /health` and does not run tasks. It is for a manual process on port 8002. Compose does not start it.

Disaggregation treats three appliances as fixed on/off loads: refrigerator 150 W, air conditioner 1500 W, water heater 4500 W. `split_power` tries every non-empty subset, keeps the largest subset that does not exceed the meter reading, and assigns the remainder to `other`. Ties keep the lowest bitmask. The four parts sum to the measured total. A 1600 W reading becomes air conditioner 1500 W and other 100 W.

### Results Service

FastAPI application `results_service.app:app`, published on port **8003**.

`GET /results/{reading_id}` loads one join of `disaggregation_results` and `energy_readings`. A row returns `200`. No row returns `404`. The service does not accept readings, publish tasks, or disaggregate.

It opens one pool at startup and does not create tables. Compose starts it after the worker is healthy so the schema already exists.

`GET /health` returns `{"status":"ok"}` without querying PostgreSQL.

### Sensor Simulator

`python -m sensor_simulator` posts synthetic readings to ingestion. Sensor ids are `sensor-00001` upward. Power is deterministic from the sensor index and the reading sequence. The tool prints how many requests returned each status, plus p50, p95, and max latency of those POSTs.

`--results-url` polls one accepted id until results returns `200` or the wait times out. The simulator never inserts into PostgreSQL itself.

## Messaging

RabbitMQ is the broker: the server that accepts and stores messages. Celery is the client and the worker framework. Ingestion uses Celery only to call `send_task`. Processing uses Celery to register and execute the task. Neither service imports the other's application code. They share the task name, the queue name, and the `ReadingAccepted` model in `energyflow_contracts`.

| Name | Value |
| --- | --- |
| Broker URL in Compose | `amqp://energyflow:energyflow@rabbitmq:5672/` |
| Queue | `energyflow.tasks` |
| Task | `energyflow.readings.process` |
| Payload | One `ReadingAccepted` object |

The worker sets `acks_late` and `reject_on_worker_lost`. The message stays unacknowledged until the task function finishes. If the worker process is lost first, the broker can redeliver it. `task_ignore_result` is on: the return value is not stored in a Celery result backend. The split lives in PostgreSQL.

RabbitMQ 4 rejects Celery's default transient, non-exclusive control queue. The worker sets `control_queue_exclusive` and `event_queue_exclusive` for that reason.

Compose does not mount a volume for RabbitMQ. Queue data does not survive recreation of that container. PostgreSQL data does, through the `energyflow-postgres` volume.

## Reliability

**A task fails because the database connection, a deadlock, or a shutdown is temporary.**

Retryable failures include connection and timeout errors, asyncpg connection errors (including too many clients), and SQL states such as `40001` (serialization failure), `40P01` (deadlock), connection failures, and administrator shutdown. The worker retries up to five times. The wait is `min(60, 2 × 2^retries)` seconds, so the scheduled waits are 2, 4, 8, 16, and 32 seconds. After that the task fails permanently and is not retried again.

**A payload can never succeed.**

`InvalidReadingError` is not retried. A body that fails validation, or a power value that cannot be disaggregated, is logged as a permanent failure. Check violations (`23514`) are also permanent.

**The worker process dies mid-task.**

Late ack plus `reject_on_worker_lost` leaves the message available for another attempt. The database, not the broker, decides whether that attempt inserts again. See Idempotency.

**Publish itself fails.**

Ingestion has no outbox and no local retry. The client does not get `202`, and no row is written, because ingestion never writes.

There is no application backpressure. If workers are slower than publishers, `energyflow.tasks` grows until RabbitMQ's own memory or disk limits intervene. Ingestion still returns `202` as long as `send_task` succeeds.

## Idempotency

Delivery is at least once, not exactly once. A task may run twice after a crash or a retry.

```text
Task received
     ↓
Result already stored for this reading_id?
     ↓ yes
Return that row. Do not disaggregate again.
     ↓ no
Disaggregate
     ↓
INSERT energy_readings ON CONFLICT (id) DO NOTHING
     ↓
INSERT disaggregation_results ON CONFLICT (reading_id) DO NOTHING
```

The id is assigned by ingestion before publish. The same message therefore names the same primary key. A second `POST` for the same sensor and timestamp allocates a new id and is a new reading. Idempotency here is per message, not per sensor.

## Data Storage

Processing applies `schema.sql` on worker startup and again on every task attempt. Both statements are `CREATE TABLE IF NOT EXISTS`.

### `energy_readings`

| Column | Notes |
| --- | --- |
| `id` | UUID primary key. The worker inserts the id from the message. |
| `sensor_id` | Same pattern and length as the API. |
| `recorded_at` | `timestamptz` |
| `power_watts` | Non-negative and finite, including a check that rejects NaN and infinities |

Index: `(sensor_id, recorded_at)`.

### `disaggregation_results`

| Column | Notes |
| --- | --- |
| `reading_id` | Primary key and foreign key to `energy_readings.id`, `ON DELETE CASCADE` |
| `total_power_watts` | Meter total stored with the split |
| `refrigerator_watts`, `air_conditioner_watts`, `water_heater_watts`, `other_watts` | Non-negative, finite |

A check requires the four appliance columns to sum to `total_power_watts` within `0.000001`.

The results API does not return `total_power_watts` as its own field. It returns `power_watts` from `energy_readings` plus the four component columns.

Connection pooling differs by service:

- Each processing attempt calls `asyncpg.create_pool` with `min_size=1` and `max_size=2`, then closes that pool.
- Results calls `create_pool` once, with asyncpg's default size, and keeps it for the life of the process.

## Scaling and Database Bottlenecks

PostgreSQL allows a limited number of clients at once (`max_connections`, 100 on a default server). Every open connection occupies one of those slots.

```text
worker concurrency
        ×
connections opened by each task
        +
results pool
        +
other clients
        =
database pressure
```

asyncpg's default pool opens 10 connections immediately. Several Celery child processes, each opening such a pool for an in-flight task, can pass `max_connections`. The server then refuses new clients with `sorry, too many clients already`. That error is classified as retryable, so the worker schedules another attempt and tries to open another pool. Retries do not add capacity when the limit is the number of connections.

The processing pool is therefore capped at one or two connections. One task runs its queries sequentially; it does not need ten connections. Compose also fixes worker concurrency at 4, instead of Celery's default of one process per CPU. Four tasks at two connections each, plus the results pool, stay under a default `max_connections`. Raising `--concurrency` without raising that limit, or widening the per-task pool back to 10, recreates the refusal.

Other ceilings, visible from the way the code is written:

- Ingestion is one process. Each request validates and publishes one message.
- `split_power` only evaluates the subsets of three on/off appliances. That work is small next to opening a connection, applying the schema, and inserting two rows on every task.
- If publish rate exceeds consume rate, `messages_ready` on `energyflow.tasks` grows. Unacknowledged messages are the ones a worker has already reserved.
- A result read is a primary-key join. More results processes do not drain the task queue.
- Nothing in the application rejects a `POST` because the queue is deep.

These are structural limits of this design. They are not a measured capacity for production traffic. A 10,000-sensor run is a simulator command, not a recorded benchmark in this repository.

## Observability

| Signal | Name | Purpose |
| --- | --- | --- |
| HTTP latency | `energyflow_http_request_duration_seconds` | Time to answer `/readings` and `/results/{reading_id}` |
| HTTP count | `energyflow_http_requests_total` | Responses by service, method, path, and status |
| Publishes | `energyflow_readings_published_total` | Tasks successfully handed to the broker |
| Task outcomes | `energyflow_tasks_total{outcome="success\|retry\|failure"}` | Worker results, including retries |
| Task time | `energyflow_task_duration_seconds` | Time inside one attempt, including database work |
| Lookups | `energyflow_result_lookups_total{outcome="hit\|miss"}` | Stored row versus `404` |

`/health` and `/metrics` are omitted from the HTTP histogram so healthchecks do not dominate it. Result paths are labeled `/results/{reading_id}` so each UUID does not become its own series.

In Compose, ingestion and results expose `/metrics` on their API ports. The worker exposes `/metrics` on port 9100. Celery runs tasks in child processes, so the worker sets `PROMETHEUS_MULTIPROC_DIR` and the metrics page aggregates those processes.

Logs are one JSON object per line on stdout, with `service`, `level`, `message`, and fields such as `request_id`, `correlation_id`, `reading_id`, and `outcome`.

Queue depth is not an application metric. Read it from RabbitMQ:

```bash
docker compose exec rabbitmq rabbitmqctl list_queues name messages messages_ready messages_unacknowledged
```

`messages_ready` are waiting. `messages_unacknowledged` have been delivered and not acked. The management UI on port 15672 shows the same queues.

Useful database checks:

```bash
docker compose exec postgres psql -U energyflow -d energyflow -c \
  "SELECT count(*) AS readings FROM energy_readings;"
docker compose exec postgres psql -U energyflow -d energyflow -c \
  "SELECT state, count(*) FROM pg_stat_activity WHERE datname = 'energyflow' GROUP BY state;"
```

Healthchecks in Compose:

| Service | Check |
| --- | --- |
| postgres | `pg_isready` |
| rabbitmq | `rabbitmq-diagnostics ping` |
| ingestion-service | `GET /health` on 8001 |
| processing-service | `GET /health` on 9100, after schema setup |
| results-service | `GET /health` on 8003 |

`depends_on` waits for these checks. Ingestion waits for RabbitMQ. Processing waits for RabbitMQ and PostgreSQL. Results waits for PostgreSQL and a healthy worker.

## Request Correlation

```mermaid
flowchart LR
    Request["HTTP request<br/>X-Request-ID"]
    Ingestion[Ingestion]
    Queue[RabbitMQ payload]
    Worker[Celery worker logs]
    Row["reading_id<br/>in PostgreSQL"]

    Request --> Ingestion
    Ingestion --> Queue
    Queue --> Worker
    Ingestion --> Row
    Worker --> Row
```

If the client sends `X-Request-ID`, ingestion keeps that value. Otherwise it generates a UUID. The response echoes the header. The same value is stored on `ReadingAccepted.correlation_id` and written to the ingestion and worker logs together with `reading_id`.

`GET /results/{reading_id}` is a separate HTTP call. It gets its own request id unless the client sends the original header again. The reading id is what connects the publish log, the worker log, and the row.

That split matters once many readings are in flight. A log line that only says "processed reading" cannot be tied to a `POST` without a shared id.

## Eventual Consistency

Accepting a reading and being able to read its split are not one transaction. Ingestion never opens PostgreSQL. The results service only sees committed rows.

```text
POST /readings
       ↓
202 Accepted          the task is on energyflow.tasks
       ↓
GET /results/{id}
       ↓
404                   the worker has not committed both rows
       ↓
worker finishes
       ↓
GET /results/{id}
       ↓
200 OK                the join exists
```

The gap can be too short to notice when a worker is idle, or long when the queue is backed up or the task is waiting out a retry. Callers should treat `404` immediately after `202` as "not stored yet or unknown", not as proof that the id was rejected.

## Testing

Tests live under `tests/` and use pytest. Async tests are enabled in `pyproject.toml`.

| Area | What it covers |
| --- | --- |
| `tests/contracts` | `EnergyReading` validation |
| `tests/ingestion` | Health, `202`, request id on the event, publish metric, `422` without publish |
| `tests/processing` | Disaggregation, idempotent use case, retry classification, Celery settings |
| `tests/results` | `200`, `404`, request id header |
| `tests/integration` | PostgreSQL constraints and one processing-to-results read |
| `tests/test_boundaries.py` | Services do not import each other's packages, and only processing contains `split_power` |
| `tests/test_observability.py` | JSON log fields and metric path labels |
| `tests/test_simulator.py` | Planned sensor ids and powers, without HTTP |

Integration tests are marked `integration` and need PostgreSQL. The default URL is `postgresql:///energyflow_test`, override with `ENERGYFLOW_DATABASE_URL`. They call the processing use case and repositories directly. They do not go through RabbitMQ.

A `rabbitmq` marker is declared in `pyproject.toml`. No test currently uses it. Broker publishing in the API tests is an in-memory fake. There is no automated end-to-end test that starts RabbitMQ and a Celery worker.

From a virtualenv with the dev extra installed:

```bash
pytest -m "not integration"
pytest -m integration
pytest
```

## Load Testing

The simulator is the load generator. It measures the HTTP accept path, not an external benchmark suite.

```bash
python -m sensor_simulator --sensors 100 --readings-per-sensor 1 --concurrency 20 \
  --results-url http://127.0.0.1:8003
```

| Flag | Meaning |
| --- | --- |
| `--sensors` | How many sensor ids to generate |
| `--readings-per-sensor` | Posts per sensor |
| `--concurrency` | How many POSTs run at once |
| `--url` | Ingestion base URL, default `http://127.0.0.1:8001` |
| `--results-url` | If set, poll one accepted id until `200` or timeout |

The report's latency numbers describe only those `POST`s:

- **p50** is the median. Half of the requests finished at or below this time.
- **p95** is the 95th percentile. Ninety-five percent finished at or below this time. It shows the slow tail that an average hides.
- **max** is the slowest request in that run.

A low p95 on `POST /readings` does not mean the split is stored. The handler returns at publish time. Queue depth and `energyflow_tasks_total` describe the work still in progress. `messages_ready` is work not yet delivered. `messages_unacknowledged` is work delivered but not acked. `outcome="success"` counts finished attempts on the worker that is currently exposing metrics.

A heavier command is available for a local experiment. It is not a recorded result in this repository, and it is not a production capacity number:

```bash
python -m sensor_simulator --sensors 10000 --readings-per-sensor 1 --concurrency 50 \
  --results-url http://127.0.0.1:8003
```

While it runs, watch `energyflow.tasks` and the task counters. Expect `202` responses before every corresponding `GET` returns `200`.

## Project Structure

```text
energy-flow/
├── docker/
│   ├── ingestion.Dockerfile
│   ├── processing.Dockerfile
│   ├── processing-entrypoint.sh
│   └── results.Dockerfile
├── src/
│   ├── energyflow_contracts/     reading and ReadingAccepted models, task and queue names
│   ├── energyflow_observability/ JSON logs, request ids, Prometheus metrics
│   ├── ingestion_service/        FastAPI accept path and Celery publisher
│   ├── processing_service/       disaggregation, Celery worker, PostgreSQL writes
│   ├── results_service/          read API
│   └── sensor_simulator/         HTTP load generator
├── tests/
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

`energyflow_contracts` is shared on purpose. The three services do not import each other's application modules. Observability is also shared. It has no disaggregation or storage rules.

## Running Locally

Docker Compose is the way to run the full system. It builds three images from this repository and pulls `postgres:16-alpine` and `rabbitmq:4-management`.

```bash
docker compose up --build
```

Compose creates one network. Service names are hostnames on that network, so application URLs use `rabbitmq` and `postgres`, not `localhost`. Inside a container, `localhost` is that container.

| From the host | Address |
| --- | --- |
| Ingestion | http://127.0.0.1:8001 |
| Results | http://127.0.0.1:8003 |
| Worker health and metrics | http://127.0.0.1:9100 |
| RabbitMQ management | http://127.0.0.1:15672 |
| PostgreSQL | `127.0.0.1:5433` |

RabbitMQ credentials are `energyflow` / `energyflow`. The `guest` user only works from inside the broker container, so Compose does not use it. PostgreSQL uses the same user and password, database `energyflow`. The host port is **5433** so it does not collide with a PostgreSQL already listening on 5432. Inside the network the host is `postgres` and the port is 5432.

Check the processes:

```bash
curl -s http://127.0.0.1:8001/health
curl -s http://127.0.0.1:8003/health
curl -s http://127.0.0.1:9100/health
```

Environment variables the processes actually read:

| Variable | Compose value | Default outside Compose |
| --- | --- | --- |
| `ENERGYFLOW_RABBITMQ_URL` | `amqp://energyflow:energyflow@rabbitmq:5672/` | `amqp://guest:guest@127.0.0.1/` |
| `ENERGYFLOW_DATABASE_URL` | `postgresql://energyflow:energyflow@postgres:5432/energyflow` | `postgresql:///energyflow_test` |
| `ENERGYFLOW_METRICS_PORT` | `9100` on the worker | `9100` |
| `PROMETHEUS_MULTIPROC_DIR` | `/tmp/prometheus` on the worker | unset |

Stop the stack:

```bash
docker compose down
```

`docker compose down -v` also deletes the `energyflow-postgres` volume and the stored readings.

### Run the processes yourself

This needs a local PostgreSQL and RabbitMQ. The defaults above point at them. The Compose hostnames do not apply.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

uvicorn ingestion_service.app:app --port 8001
uvicorn results_service.app:app --port 8003
celery -A processing_service.worker:celery_app worker --loglevel=info
```

Optional: `uvicorn processing_service.health:app --port 8002` for the health-only app. The worker's own health port is 9100 once the worker is ready.

## API

### Create a reading

`POST http://127.0.0.1:8001/readings`

```http
POST /readings HTTP/1.1
Content-Type: application/json
X-Request-ID: demo-1

{
  "sensor_id": "sensor-001",
  "timestamp": "2026-09-30T22:25:00Z",
  "power_watts": 1600
}
```

`202 Accepted`:

```json
{
  "id": "9cd62c05-a245-499e-aadc-de3f96ed4bab",
  "sensor_id": "sensor-001",
  "timestamp": "2026-09-30T22:25:00Z",
  "power_watts": 1600.0,
  "status": "accepted"
}
```

The `id` is generated per request. The response header `X-Request-ID` is `demo-1`, and that value is the event's `correlation_id`.

`422` for a negative power, a naive timestamp, an illegal sensor id, or an extra field. Those requests are not published.

### Read a result

`GET http://127.0.0.1:8003/results/{reading_id}`

After the worker stores the 1600 W example:

```json
{
  "reading_id": "9cd62c05-a245-499e-aadc-de3f96ed4bab",
  "sensor_id": "sensor-001",
  "timestamp": "2026-09-30T22:25:00Z",
  "power_watts": 1600.0,
  "refrigerator_watts": 0.0,
  "air_conditioner_watts": 1500.0,
  "water_heater_watts": 0.0,
  "other_watts": 100.0
}
```

`404` when that id is not stored yet, or was never accepted. `422` when the path is not a UUID.

### Health and metrics

| Method | URL |
| --- | --- |
| `GET` | http://127.0.0.1:8001/health |
| `GET` | http://127.0.0.1:8001/metrics |
| `GET` | http://127.0.0.1:8003/health |
| `GET` | http://127.0.0.1:8003/metrics |
| `GET` | http://127.0.0.1:9100/health |
| `GET` | http://127.0.0.1:9100/metrics |

There is no authentication on any endpoint.

## Design Decisions

### Why FastAPI?

The HTTP edge has to validate JSON and return `202`, `404`, or `422` without embedding Celery or SQL in the route. FastAPI plus Pydantic does that validation before the handler. The ingestion handler only publishes.

The alternative was a single function that both served HTTP and disaggregated. That hides the queue. The trade-off is two HTTP code paths to deploy, and a results API that cannot see unpublished work.

### Why async/await?

Ingestion waits on publish, and the database calls are asyncpg. Those waits should yield the event loop. `split_power` stays synchronous and is moved to a thread, because it is CPU work, not I/O.

Calling blocking `send_task` directly on the event loop would stall other requests in that process. The trade-off is a small thread hop on every accept.

### Why RabbitMQ?

Something has to hold the message between `202` and a worker that may be busy or restarting. A queue is that buffer. The project already uses Celery, and Celery's broker here is RabbitMQ.

The alternative was processing inside the request. Then a slow database would slow every `POST`. The trade-off is operational: a broker to run, and a window where the result is not readable yet.

### Why Celery?

The worker needs a named task, retries with delay, and ack behavior when a process dies. Celery provides that on top of RabbitMQ. Ingestion only needs `send_task`, so it does not import the worker function.

The alternative was a hand-written consumer. That would make retry and ack policy code this repository would have to own. The trade-off is Celery's process model: prefork children, a control queue that RabbitMQ 4 rejects unless it is exclusive, and metrics that must be aggregated across processes.

### Why PostgreSQL?

The split has to outlive the worker and be readable by another service, with a primary key and checks that the parts sum to the total. PostgreSQL is the system of record. asyncpg is the async driver.

The alternative was keeping results in the worker's memory. A restart would drop them, and the results service could not see them. The trade-off is a shared schema between writer and reader, and connection limits that show up under concurrency.

### Why these service boundaries?

Ingestion, processing, and results change for different reasons and fail independently. A stopped worker does not stop `202` responses, as long as RabbitMQ is up. A stopped results API does not stop inserts.

The alternative was one process with three modules. That is simpler to run and was an earlier shape of this codebase. The trade-off of the split is a shared database and a duplicated read query, instead of the results service importing the processing repositories.

### Why Docker Compose?

The demonstration needs five processes and stable hostnames. Compose provides the network, health-gated startup, and the published ports.

Kubernetes would schedule the same processes. It would not change the per-task connection cost or the single queue. The trade-off is that this Compose file is a local runtime: one replica of each service, no rolling deploy, and RabbitMQ without a data volume.

### Why idempotency on `reading_id`?

At-least-once delivery means the same task can run twice. The primary key and `ON CONFLICT DO NOTHING`, plus the "return the existing result" check, keep one logical reading as one row.

The alternative was exactly-once delivery from the broker. This stack does not provide that. The trade-off is that a new HTTP request is always a new id, even when the sensor payload repeats.

### Why retries with backoff?

A dead connection or a deadlock may succeed on a later attempt. Immediate permanent failure would drop the reading. Five attempts with waits of 2, 4, 8, 16, and 32 seconds give the dependency time to return.

The alternative was an infinite retry. That can pin a poison message and, in the too-many-clients case, keep opening pools. Invalid payloads are excluded so they do not use those attempts. The trade-off is that a task which exhausts retries is finished from the queue's point of view and is still absent from the database. The client is not notified, except by a continued `404`.

## Trade-offs and Limitations

This repository is a hands-on backend exercise. The boundaries and failure behavior are real. Several production concerns are intentionally out of scope.

- **One PostgreSQL database** for the writer and the reader. The schema is the contract between them. A private database per service would remove that coupling and force another way to expose results.
- **No authentication or authorization.** Any client that can reach the ports can post readings and read results.
- **No cloud deployment, autoscaling, or Kubernetes.** Compose runs a single local copy of each service.
- **RabbitMQ is local and has no Compose volume.** Recreating the broker container drops whatever is still queued.
- **No outbox.** A crash after publish and before the `202` is written to the client is not coordinated with a database transaction, because ingestion has no database write.
- **`404` is ambiguous** between "not processed yet" and "unknown id".
- **The disaggregation model is fixed on/off wattages**, not a measured appliance signature from a real meter.
- **Metrics are plain text endpoints.** Nothing in the repo scrapes them into Prometheus or draws them in Grafana.
- **The results pool still uses asyncpg's default size.** Only the per-task processing pool is capped at 1–2 connections.
- **Every task re-applies the schema** after opening its pool. That is simple and repetitive.
- **Load numbers depend on the machine.** The simulator can drive 100 or 10,000 sensors. This README does not publish those runs as a capacity guarantee.
- **No automated test drives the full broker path.** Confidence in RabbitMQ plus Celery comes from the worker configuration tests and from running Compose.

These choices keep the system small enough to run and inspect. They are the wrong defaults for an internet-facing deployment.

## Engineering Concepts Demonstrated

- Python services with a shared contract and separate application packages
- FastAPI request validation and explicit status codes
- Pydantic models at the boundary and in the disaggregation domain
- `async`/`await` for broker and database waits, with CPU work moved to a thread
- A Celery task as the unit of background work
- RabbitMQ as the buffer between accept and process
- PostgreSQL constraints, a foreign key, and an index
- Connection pooling and the interaction with `max_connections`
- Retries with exponential backoff, and errors that must not be retried
- Idempotent writes under at-least-once delivery
- Eventual consistency between `202` and a later `200`
- JSON logs and `X-Request-ID` / `correlation_id`
- Application metrics for HTTP latency, publishes, task outcomes, and lookups
- Docker Compose healthchecks and service DNS
- pytest coverage of the domain, the HTTP edges, and PostgreSQL
- A sensor simulator for a local concurrent load
