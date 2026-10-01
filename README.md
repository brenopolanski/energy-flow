# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

The project currently contains the Python skeleton, an `EnergyReading` domain model, a disaggregation service, and a FastAPI application. `POST /readings` awaits the service. The appliance split itself stays synchronous. Later stages will add background jobs, messaging, and a database.

## Requirements

- Python 3.12 or newer

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Tests

```bash
pytest
```

## API

```bash
uvicorn energyflow.api.app:app --port 8000
```

- `GET /health`
- `POST /readings`
