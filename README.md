# EnergyFlow

EnergyFlow is a toy distributed energy-data processing system. It is a learning project and will be built in small stages.

Later stages will add services, async APIs, background jobs, messaging, and a database. This stage only sets up the Python project: a src layout, package metadata, and pytest.

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
