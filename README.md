# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

The project currently contains the Python skeleton and an `EnergyReading` domain model validated with Pydantic. Later stages will add services, async APIs, background jobs, messaging, and a database.

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
