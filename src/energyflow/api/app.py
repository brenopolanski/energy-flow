"""EnergyFlow HTTP application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from energyflow import __version__
from energyflow.api.routes import router
from energyflow.jobs import ReadingJobDispatcher
from energyflow.persistence.postgres import (
    DEFAULT_DATABASE_URL,
    PostgresEnergyReadingRepository,
    connect,
)
from energyflow.persistence.repository import EnergyReadingRepository
from energyflow.worker import CeleryReadingJobDispatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("ENERGYFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)
    pool = await connect(database_url)
    app.state.readings = PostgresEnergyReadingRepository(pool)
    app.state.jobs = CeleryReadingJobDispatcher()
    try:
        yield
    finally:
        await pool.close()


def create_app(
    readings: EnergyReadingRepository | None = None,
    jobs: ReadingJobDispatcher | None = None,
) -> FastAPI:
    if (readings is None) != (jobs is None):
        raise ValueError("readings and jobs must be provided together")
    app = FastAPI(
        title="EnergyFlow",
        version=__version__,
        lifespan=None if readings is not None else lifespan,
    )
    app.include_router(router)
    if readings is not None and jobs is not None:
        app.state.readings = readings
        app.state.jobs = jobs
    return app


app = create_app()
