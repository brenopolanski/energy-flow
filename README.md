# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

The project currently contains the Python skeleton, an `EnergyReading` domain model, a disaggregation service, a FastAPI application, a PostgreSQL repository, a RabbitMQ publisher/consumer, and a Celery worker. `POST /readings` stores the reading and enqueues `energyflow.process_energy_reading`. The worker loads that row, validates it, runs disaggregation, and stores one result. RabbitMQ is the Celery broker. The task queue is `energyflow.tasks`, separate from the `energy_readings` queue.

## Requirements

- Python 3.12 or newer

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

RabbitMQ tests use `ENERGYFLOW_RABBITMQ_URL`. The default is `amqp://guest:guest@127.0.0.1/`.

```bash
pytest -m rabbitmq
```

The stage 7 consumer listens on the `energy_readings` queue. `POST /readings` does not publish to that queue anymore:

```bash
python -m energyflow.messaging
```

## Worker

Celery uses `ENERGYFLOW_RABBITMQ_URL` (default `amqp://guest:guest@127.0.0.1/`) and stores results with `ENERGYFLOW_DATABASE_URL` (default `postgresql:///energyflow_test`).

```bash
celery -A energyflow.worker:celery_app worker --loglevel=info
```

A stored result is keyed by the reading id. Running the task again returns that row. A missing reading, an invalid id, or a row that fails validation is a permanent failure. Connection and deadlock failures retry up to 5 times, waiting 2, 4, 8, 16, then 32 seconds.

## API

```bash
uvicorn energyflow.api.app:app --port 8000
```

- `GET /health`
- `POST /readings` stores the reading and returns `202 Accepted` with its id. Disaggregation runs in the worker.
