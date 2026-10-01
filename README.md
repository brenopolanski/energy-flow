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

Kubernetes is not part of this stage.

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
