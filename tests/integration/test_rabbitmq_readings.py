"""Publishing and consuming accepted readings through RabbitMQ.

These tests need a broker. Set ENERGYFLOW_RABBITMQ_URL or use the local default.
"""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import aio_pika
import pytest

from energyflow.messaging.events import EnergyReadingAccepted
from energyflow.messaging.rabbitmq import (
    DEFAULT_URL,
    MAX_ATTEMPTS,
    RabbitMQReadingConsumer,
    ReadingTopology,
    connect,
    declare_topology,
    open_publisher,
)
from energyflow.models import EnergyReading

pytestmark = pytest.mark.rabbitmq

BROKER_URL = os.environ.get("ENERGYFLOW_RABBITMQ_URL", DEFAULT_URL)
TIMESTAMP = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
async def broker():
    suffix = uuid4().hex
    topology = ReadingTopology(
        exchange_name=f"energyflow.test.{suffix}",
        queue_name=f"energy_readings.test.{suffix}",
        routing_key=f"energy.reading.accepted.{suffix}",
    )
    try:
        connection = await connect(BROKER_URL)
    except Exception as exc:
        pytest.skip(f"RabbitMQ is not available: {exc}")
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    exchange, queue = await declare_topology(channel, topology)
    publisher = await open_publisher(channel, topology)
    try:
        yield publisher, exchange, queue, topology
    finally:
        await queue.delete(if_unused=False, if_empty=False)
        await exchange.delete()
        await connection.close()


def _reading() -> EnergyReading:
    return EnergyReading(
        sensor_id="sensor-001",
        timestamp=TIMESTAMP,
        power_watts=1600,
    )


async def test_publish_is_consumed_and_acknowledged(broker) -> None:
    publisher, exchange, queue, topology = broker
    received: list[EnergyReadingAccepted] = []
    done = asyncio.Event()

    async def handler(event: EnergyReadingAccepted) -> None:
        received.append(event)
        done.set()

    await RabbitMQReadingConsumer(
        exchange,
        queue,
        topology.routing_key,
        handler,
    ).start()
    await publisher.publish_reading_accepted(_reading())
    await asyncio.wait_for(done.wait(), timeout=5)

    assert received[0].sensor_id == "sensor-001"
    assert received[0].power_watts == 1600
    assert received[0].timestamp == TIMESTAMP
    await _wait_until_empty(queue)


async def test_malformed_message_is_dropped_and_the_next_one_is_consumed(
    broker,
) -> None:
    publisher, exchange, queue, topology = broker
    received: list[EnergyReadingAccepted] = []
    done = asyncio.Event()

    async def handler(event: EnergyReadingAccepted) -> None:
        received.append(event)
        done.set()

    await RabbitMQReadingConsumer(
        exchange,
        queue,
        topology.routing_key,
        handler,
    ).start()
    await exchange.publish(
        aio_pika.Message(body=b"not-json", content_type="application/json"),
        routing_key=topology.routing_key,
    )
    await publisher.publish_reading_accepted(_reading())
    await asyncio.wait_for(done.wait(), timeout=5)

    assert len(received) == 1
    assert received[0].sensor_id == "sensor-001"
    await _wait_until_empty(queue)


async def test_handler_failure_is_retried_then_acknowledged(broker) -> None:
    _publisher, exchange, queue, topology = broker
    calls = 0
    done = asyncio.Event()

    async def handler(_event: EnergyReadingAccepted) -> None:
        nonlocal calls
        calls += 1
        if calls < MAX_ATTEMPTS:
            raise RuntimeError("temporary")
        done.set()

    consumer = RabbitMQReadingConsumer(
        exchange,
        queue,
        topology.routing_key,
        handler,
    )
    await consumer.start()
    reading = _reading()
    event = EnergyReadingAccepted.from_reading(reading)
    await exchange.publish(
        aio_pika.Message(
            body=event.to_json().encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=topology.routing_key,
    )
    await asyncio.wait_for(done.wait(), timeout=5)

    assert calls == MAX_ATTEMPTS
    await _wait_until_empty(queue)


async def _wait_until_empty(queue) -> None:
    for _ in range(50):
        declaration = await queue.channel.declare_queue(queue.name, passive=True)
        if declaration.declaration_result.message_count == 0:
            return
        await asyncio.sleep(0.05)
    remaining = await queue.channel.declare_queue(queue.name, passive=True)
    raise AssertionError(
        f"queue {queue.name} still has {remaining.declaration_result.message_count} messages"
    )
