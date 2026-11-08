import asyncio
import json
import logging
from contextlib import asynccontextmanager

import httpx
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
from pydantic import ValidationError

from services.common.config import (
    DEAD_LETTER_TOPIC,
    INVENTORY_URL,
    KAFKA_BOOTSTRAP_SERVERS,
    SHOP_EVENTS_TOPIC,
)
from services.common.events import ShopEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def publish_warnings(producer: AIOKafkaProducer) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                response = await client.get(f"{INVENTORY_URL}/internal/warnings/pending")
                response.raise_for_status()
                for warning in response.json():
                    await producer.send_and_wait(
                        "shop-notifications",
                        json.dumps(warning).encode("utf-8"),
                        key=warning["shop_id"].encode("utf-8"),
                    )
                    await client.put(
                        f"{INVENTORY_URL}/internal/warnings/{warning['warning_id']}/published"
                    )
            except Exception:
                logger.exception("Warning outbox delivery failed; it will be retried")
            await asyncio.sleep(1)


async def consume_events(app) -> None:
    consumer = app.state.consumer
    producer = app.state.producer
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            message = await consumer.getone()
            try:
                event = json.loads(message.value)
                validated_event = ShopEvent.model_validate(event)
                response = await client.post(
                    f"{INVENTORY_URL}/internal/events",
                    json=validated_event.model_dump(mode="json"),
                )
                response.raise_for_status()
            except (ValueError, json.JSONDecodeError, ValidationError) as error:
                dead_letter = {
                    "raw": message.value.decode("utf-8", errors="replace"),
                    "error": str(error),
                }
                await producer.send_and_wait(
                    DEAD_LETTER_TOPIC,
                    json.dumps(dead_letter).encode("utf-8"),
                    key=message.key,
                )
            except httpx.HTTPStatusError as error:
                if error.response.status_code < 500:
                    dead_letter = {
                        "raw": message.value.decode("utf-8", errors="replace"),
                        "error": str(error),
                    }
                    await producer.send_and_wait(
                        DEAD_LETTER_TOPIC,
                        json.dumps(dead_letter).encode("utf-8"),
                        key=message.key,
                    )
                else:
                    logger.exception("Inventory service failed; retrying the same Kafka offset")
                    consumer.seek(TopicPartition(message.topic, message.partition), message.offset)
                    await asyncio.sleep(2)
                    continue
            except Exception:
                logger.exception("Event persistence failed; retrying the same Kafka offset")
                consumer.seek(TopicPartition(message.topic, message.partition), message.offset)
                await asyncio.sleep(2)
                continue
            await consumer.commit()


@asynccontextmanager
async def lifespan(app):
    app.state.producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await app.state.producer.start()
    app.state.consumer = AIOKafkaConsumer(
        SHOP_EVENTS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="sales-processor",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await app.state.consumer.start()
    app.state.outbox_task = asyncio.create_task(publish_warnings(app.state.producer))
    app.state.consumer_task = asyncio.create_task(consume_events(app))
    yield
    app.state.consumer_task.cancel()
    app.state.outbox_task.cancel()
    await app.state.consumer.stop()
    await app.state.producer.stop()


from fastapi import FastAPI

app = FastAPI(title="Sales Processor", lifespan=lifespan)


@app.get("/health/live")
async def live():
    if app.state.consumer_task.done() or app.state.outbox_task.done():
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="processor background task has stopped")
    return {"status": "alive"}