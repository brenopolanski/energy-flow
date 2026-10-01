"""EnergyFlow HTTP application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from energyflow import __version__
from energyflow.api.routes import router
from energyflow.messaging.publisher import ReadingEventPublisher
from energyflow.messaging.rabbitmq import DEFAULT_URL, connect, open_publisher


@asynccontextmanager
async def rabbitmq_lifespan(app: FastAPI):
    url = os.environ.get("ENERGYFLOW_RABBITMQ_URL", DEFAULT_URL)
    connection = await connect(url)
    channel = await connection.channel()
    app.state.publisher = await open_publisher(channel)
    try:
        yield
    finally:
        await connection.close()


def create_app(publisher: ReadingEventPublisher | None = None) -> FastAPI:
    app = FastAPI(
        title="EnergyFlow",
        version=__version__,
        lifespan=None if publisher is not None else rabbitmq_lifespan,
    )
    app.include_router(router)
    if publisher is not None:
        app.state.publisher = publisher
    return app


app = create_app()
