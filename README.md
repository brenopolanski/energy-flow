# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

The project currently contains the Python skeleton, an `EnergyReading` domain model, a disaggregation service, a FastAPI application, a PostgreSQL repository, and a RabbitMQ publisher/consumer for accepted readings. `POST /readings` publishes `energy_reading.accepted` after the reading is processed. Later stages will add background workers.

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

The consumer listens on the `energy_readings` queue:

```bash
python -m energyflow.messaging
```

## API

```bash
uvicorn energyflow.api.app:app --port 8000
```

- `GET /health`
- `POST /readings`
