"""RabbitMQ publisher and consumer for accepted energy readings."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractIncomingMessage, AbstractQueue
from pydantic import ValidationError

from energyflow.messaging.events import EnergyReadingAccepted
from energyflow.models import EnergyReading

DEFAULT_EXCHANGE = "energyflow"
DEFAULT_QUEUE = "energy_readings"
DEFAULT_ROUTING_KEY = "energy.reading.accepted"
DEFAULT_URL = "amqp://guest:guest@127.0.0.1/"
MAX_ATTEMPTS = 3

ReadingHandler = Callable[[EnergyReadingAccepted], Awaitable[None]]


@dataclass(frozen=True)
class ReadingTopology:
    """Exchange, queue, and routing key used for accepted readings."""

    exchange_name: str = DEFAULT_EXCHANGE
    queue_name: str = DEFAULT_QUEUE
    routing_key: str = DEFAULT_ROUTING_KEY


class _Delivery(Protocol):
    body: bytes
    headers: dict[str, object] | None

    async def ack(self) -> None: ...

    async def reject(self, requeue: bool = False) -> None: ...


class RabbitMQReadingPublisher:
    """Publishes accepted readings to the direct exchange."""

    def __init__(self, exchange: AbstractExchange, routing_key: str) -> None:
        self._exchange = exchange
        self._routing_key = routing_key

    async def publish_reading_accepted(self, reading: EnergyReading) -> None:
        event = EnergyReadingAccepted.from_reading(reading)
        await self._publish(event.to_json().encode(), attempt=1)

    async def _publish(self, body: bytes, *, attempt: int) -> None:
        headers = {"x-attempt": attempt} if attempt > 1 else None
        await self._exchange.publish(
            Message(
                body=body,
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                headers=headers,
            ),
            routing_key=self._routing_key,
        )


class RabbitMQReadingConsumer:
    """Receives accepted-reading events and acknowledges each delivery."""

    def __init__(
        self,
        exchange: AbstractExchange,
        queue: AbstractQueue,
        routing_key: str,
        handler: ReadingHandler,
        *,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._exchange = exchange
        self._queue = queue
        self._routing_key = routing_key
        self._handler = handler
        self._max_attempts = max_attempts

    async def start(self) -> None:
        await self._queue.consume(self._on_message)

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        await handle_delivery(
            message,
            handler=self._handler,
            republish=self._republish,
            max_attempts=self._max_attempts,
        )

    async def _republish(self, body: bytes, attempt: int) -> None:
        await self._exchange.publish(
            Message(
                body=body,
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                headers={"x-attempt": attempt},
            ),
            routing_key=self._routing_key,
        )


async def declare_topology(
    channel: AbstractChannel,
    topology: ReadingTopology | None = None,
) -> tuple[AbstractExchange, AbstractQueue]:
    """Declare the durable direct exchange, queue, and binding."""
    selected = topology or ReadingTopology()
    exchange = await channel.declare_exchange(
        selected.exchange_name,
        ExchangeType.DIRECT,
        durable=True,
    )
    queue = await channel.declare_queue(selected.queue_name, durable=True)
    await queue.bind(exchange, routing_key=selected.routing_key)
    return exchange, queue


async def open_publisher(
    channel: AbstractChannel,
    topology: ReadingTopology | None = None,
) -> RabbitMQReadingPublisher:
    """Declare the topology and return a publisher bound to it."""
    selected = topology or ReadingTopology()
    exchange, _queue = await declare_topology(channel, selected)
    return RabbitMQReadingPublisher(exchange, selected.routing_key)


async def handle_delivery(
    message: _Delivery,
    *,
    handler: ReadingHandler,
    republish: Callable[[bytes, int], Awaitable[None]],
    max_attempts: int = MAX_ATTEMPTS,
) -> None:
    """Ack a valid event, drop a malformed one, and retry handler failures."""
    try:
        event = EnergyReadingAccepted.from_json(message.body)
    except (ValidationError, UnicodeDecodeError, ValueError):
        await message.reject(requeue=False)
        return

    try:
        await handler(event)
    except Exception:
        attempt = _attempt_number(message.headers)
        if attempt >= max_attempts:
            await message.reject(requeue=False)
            return
        await republish(message.body, attempt + 1)
        await message.ack()
        return

    await message.ack()


def _attempt_number(headers: dict[str, object] | None) -> int:
    if not headers:
        return 1
    raw = headers.get("x-attempt", 1)
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return value if value >= 1 else 1


async def connect(url: str = DEFAULT_URL) -> aio_pika.abc.AbstractRobustConnection:
    """Open a connection that reconnects after a broker outage."""
    return await aio_pika.connect_robust(url)
