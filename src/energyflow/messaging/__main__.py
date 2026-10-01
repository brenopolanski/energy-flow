"""Run the accepted-reading consumer.

    python -m energyflow.messaging
"""

import asyncio
import os

import aio_pika

from energyflow.messaging.events import EnergyReadingAccepted
from energyflow.messaging.rabbitmq import (
    DEFAULT_ROUTING_KEY,
    DEFAULT_URL,
    RabbitMQReadingConsumer,
    declare_topology,
)


async def _handle(event: EnergyReadingAccepted) -> None:
    print(event.to_json(), flush=True)


async def _main() -> None:
    url = os.environ.get("ENERGYFLOW_RABBITMQ_URL", DEFAULT_URL)
    connection = await aio_pika.connect_robust(url)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    exchange, queue = await declare_topology(channel)
    consumer = RabbitMQReadingConsumer(
        exchange,
        queue,
        DEFAULT_ROUTING_KEY,
        _handle,
    )
    await consumer.start()
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(_main())
