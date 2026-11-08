import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import httpx
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
from fastapi import FastAPI, HTTPException, Query

from services.common.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    READ_API_URL,
    SHOP_EVENTS_TOPIC,
    SHOP_NOTIFICATIONS_TOPIC,
)
from services.common.events import ShopEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
SHOP_IDS = [shop.strip() for shop in os.getenv("SHOP_IDS", "shop-a,shop-b,shop-n").split(",") if shop.strip()]


async def route_notifications(app: FastAPI) -> None:
    consumer = app.state.notification_consumer
    while True:
        message = await consumer.getone()
        try:
            warning = json.loads(message.value)
            shop_id = warning["shop_id"]
            if shop_id not in SHOP_IDS:
                raise ValueError(f"No configured route for shop {shop_id!r}")
            target = f"http://warning-handler.{shop_id}.svc.cluster.local:8080/warnings"
            if os.getenv("ENVIRONMENT", "local") == "local":
                target = f"http://warning-handler-{shop_id}:8080/warnings"
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(target, json=warning)
                response.raise_for_status()
            await consumer.commit()
        except Exception:
            logger.exception("Notification delivery failed; Kafka will redeliver it")
            consumer.seek(TopicPartition(message.topic, message.partition), message.offset)
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await app.state.producer.start()
    app.state.notification_consumer = AIOKafkaConsumer(
        SHOP_NOTIFICATIONS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="gateway-notifications",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await app.state.notification_consumer.start()
    app.state.notification_task = asyncio.create_task(route_notifications(app))
    yield
    app.state.notification_task.cancel()
    await app.state.notification_consumer.stop()
    await app.state.producer.stop()


app = FastAPI(title="Shop Gateway", lifespan=lifespan)


@app.get("/health/live")
async def live() -> dict[str, str]:
    if app.state.notification_task.done():
        raise HTTPException(status_code=503, detail="notification consumer has stopped")
    return {"status": "alive"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{READ_API_URL}/health/ready")
        response.raise_for_status()
    except Exception as error:
        raise HTTPException(status_code=503, detail="gateway dependencies are not ready") from error
    return {"status": "ready"}


@app.post("/events", status_code=202)
async def publish_event(event: ShopEvent) -> dict[str, str]:
    if event.shop_id not in SHOP_IDS:
        raise HTTPException(status_code=422, detail="unknown shop_id")
    await app.state.producer.send_and_wait(
        SHOP_EVENTS_TOPIC,
        event.model_dump_json().encode("utf-8"),
        key=event.shop_id.encode("utf-8"),
    )
    return {"event_id": str(event.event_id), "status": "published"}


async def proxy_get(path: str, params: dict | None = None):
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{READ_API_URL}{path}", params=params)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="read service unavailable") from error
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=response.json().get("detail", "not found"))
    response.raise_for_status()
    return response.json()


@app.get("/products")
async def products(in_stock: bool = Query(default=False)):
    return await proxy_get("/products", {"in_stock": in_stock})


@app.get("/products/{product_id}")
async def product(product_id: str):
    return await proxy_get(f"/products/{product_id}")


@app.get("/shops/{shop_id}/sales/total")
async def shop_revenue(shop_id: str):
    return await proxy_get(f"/shops/{shop_id}/sales/total")


@app.get("/market/sales/total")
async def market_revenue():
    return await proxy_get("/market/sales/total")


@app.get("/orders/{order_id}")
async def order_status(order_id: str):
    return await proxy_get(f"/orders/{order_id}")