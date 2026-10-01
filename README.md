# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

The project currently contains the Python skeleton, an `EnergyReading` domain model, a disaggregation service, a FastAPI application, and a PostgreSQL repository for energy readings. The domain and the HTTP routes do not import the database driver. Later stages will add background jobs and messaging.

## Requirements

- Python 3.12 or newer

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Tests

Unit tests do not need a database:

```bash
pytest -m "not integration"
```

Integration tests need PostgreSQL and `ENERGYFLOW_DATABASE_URL`. The default is `postgresql:///energyflow_test`.

```bash
pytest -m integration
```

## API

```bash
uvicorn energyflow.api.app:app --port 8000
```

- `GET /health`
- `POST /readings`
