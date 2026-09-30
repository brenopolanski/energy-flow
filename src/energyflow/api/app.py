"""EnergyFlow HTTP application."""

from fastapi import FastAPI

from energyflow import __version__
from energyflow.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="EnergyFlow", version=__version__)
    app.include_router(router)
    return app


app = create_app()
