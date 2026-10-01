"""Health endpoint for the processing service.

The Celery worker is a separate process. This application only reports that
the service package is up. It does not disaggregate or read results.
"""

from fastapi import FastAPI, status
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    app = FastAPI(title="EnergyFlow Processing", version="0.1.0")

    @app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
