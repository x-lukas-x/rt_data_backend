from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from services.common.config import DATABASE_URL
from services.common.events import ShopEvent
from services.inventory.rules import should_create_warning

MIGRATION_DIR = Path(__file__).parent / "migrations"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    await apply_migrations(app.state.pool)
    yield
    await app.state.pool.close()


app = FastAPI(title="Inventory Service", lifespan=lifespan)


async def apply_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version INTEGER PRIMARY KEY,
                   applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        for migration_path in sorted(MIGRATION_DIR.glob("*.sql")):
            version = int(migration_path.name.split("_", maxsplit=1)[0])
            async with connection.transaction():
                applied = await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version = $1)", version
                )
                if applied:
                    continue
                await connection.execute(migration_path.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES($1)", version
                )


class EventResult(BaseModel):
    event_id: str
    status: str
    product_id: str
    stock_quantity: int | None = None
    message: str | None = None


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    async with app.state.pool.acquire() as connection:
        imported = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM import_runs WHERE import_name = 'initial_inventory')"
        )
    if not imported:
        raise HTTPException(status_code=503, detail="initial inventory import is pending")
    return {"status": "ready"}


@app.get("/internal/products")
async def products(in_stock: bool = False) -> list[dict[str, Any]]:
    condition = "WHERE stock_quantity > 0" if in_stock else ""
    async with app.state.pool.acquire() as connection:
        rows = await connection.fetch(
            f"SELECT product_id, product_name, stock_quantity, unit_price FROM products {condition} ORDER BY product_id"
        )
    return [dict(row) for row in rows]


@app.get("/internal/products/{product_id}")
async def product(product_id: str) -> dict[str, Any]:
    async with app.state.pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT product_id, product_name, stock_quantity, unit_price FROM products WHERE product_id = $1",
            product_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")
    return dict(row)


@app.post("/internal/events", response_model=EventResult)
async def process_event(event: ShopEvent) -> EventResult:
    event_id = str(event.event_id)
    product_id = event.payload["product_id"]
    async with app.state.pool.acquire() as connection:
        async with connection.transaction():
            inserted = await connection.fetchval(
                """INSERT INTO processed_events(event_id, event_type, shop_id, status, product_id)
                   VALUES($1, $2, $3, 'processing', $4)
                   ON CONFLICT (event_id) DO NOTHING RETURNING event_id""",
                event_id,
                event.event_type,
                event.shop_id,
                product_id,
            )
            if inserted is None:
                previous = await connection.fetchrow(
                    "SELECT event_id, status, product_id, message FROM processed_events WHERE event_id = $1",
                    event_id,
                )
                return EventResult(**dict(previous))

            if event.event_type == "product_sold":
                result = await _process_sale(connection, event, product_id)
            else:
                result = await _process_restock(connection, event, product_id)
    return result


async def _reject(
    connection: asyncpg.Connection,
    event_id: str,
    product_id: str,
    message: str,
) -> EventResult:
    await connection.execute(
        "UPDATE processed_events SET status = 'rejected', message = $2 WHERE event_id = $1",
        event_id,
        message,
    )
    return EventResult(event_id=event_id, status="rejected", product_id=product_id, message=message)


async def _process_sale(
    connection: asyncpg.Connection, event: ShopEvent, product_id: str
) -> EventResult:
    row = await connection.fetchrow(
        """UPDATE products SET stock_quantity = stock_quantity - 1
           WHERE product_id = $1 AND stock_quantity > 0
           RETURNING stock_quantity, unit_price""",
        product_id,
    )
    if row is None:
        return await _reject(connection, str(event.event_id), product_id, "product missing or out of stock")

    amount = row["unit_price"]
    await connection.execute(
        "INSERT INTO sales(event_id, shop_id, product_id, amount) VALUES($1, $2, $3, $4)",
        str(event.event_id),
        event.shop_id,
        product_id,
        amount,
    )
    await connection.execute(
        "UPDATE market_revenue SET amount = amount + $1 WHERE singleton = TRUE", amount
    )
    await connection.execute(
        """INSERT INTO shop_revenue(shop_id, amount) VALUES($1, $2)
           ON CONFLICT (shop_id) DO UPDATE SET amount = shop_revenue.amount + EXCLUDED.amount""",
        event.shop_id,
        amount,
    )
    await connection.execute(
        "UPDATE processed_events SET status = 'accepted' WHERE event_id = $1",
        str(event.event_id),
    )
    if should_create_warning(row["stock_quantity"]):
        await connection.execute(
            """INSERT INTO warning_outbox(
                   warning_id, source_event_id, shop_id, product_id, stock_quantity
               ) VALUES($1, $2, $3, $4, $5) ON CONFLICT (source_event_id) DO NOTHING""",
            f"warning-{event.event_id}",
            str(event.event_id),
            event.shop_id,
            product_id,
            row["stock_quantity"],
        )
    return EventResult(
        event_id=str(event.event_id),
        status="accepted",
        product_id=product_id,
        stock_quantity=row["stock_quantity"],
    )


async def _process_restock(
    connection: asyncpg.Connection, event: ShopEvent, product_id: str
) -> EventResult:
    row = await connection.fetchrow(
        "UPDATE products SET stock_quantity = stock_quantity + 100 WHERE product_id = $1 RETURNING stock_quantity",
        product_id,
    )
    if row is None:
        return await _reject(connection, str(event.event_id), product_id, "product not found")
    await connection.execute(
        "INSERT INTO restocks(event_id, shop_id, product_id, quantity) VALUES($1, $2, $3, 100)",
        str(event.event_id),
        event.shop_id,
        product_id,
    )
    await connection.execute(
        "UPDATE processed_events SET status = 'accepted' WHERE event_id = $1",
        str(event.event_id),
    )
    return EventResult(
        event_id=str(event.event_id),
        status="accepted",
        product_id=product_id,
        stock_quantity=row["stock_quantity"],
    )


@app.get("/internal/revenue")
async def revenue(shop_id: str | None = None) -> dict[str, Any]:
    async with app.state.pool.acquire() as connection:
        if shop_id:
            amount = await connection.fetchval(
                "SELECT amount FROM shop_revenue WHERE shop_id = $1", shop_id
            )
            return {"shop_id": shop_id, "total": amount or 0}
        amount = await connection.fetchval(
            "SELECT amount FROM market_revenue WHERE singleton = TRUE"
        )
    return {"total": amount or 0}


@app.get("/internal/events/{event_id}")
async def event_status(event_id: str) -> dict[str, Any]:
    async with app.state.pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT event_id, event_type, shop_id, status, product_id, message FROM processed_events WHERE event_id = $1",
            event_id,
        )
    if row is None:
        return {"event_id": event_id, "status": "pending"}
    return dict(row)


@app.get("/internal/warnings/pending")
async def pending_warnings(limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    async with app.state.pool.acquire() as connection:
        rows = await connection.fetch(
            """SELECT warning_id, shop_id, product_id, stock_quantity
               FROM warning_outbox WHERE published_at IS NULL ORDER BY warning_id LIMIT $1""",
            limit,
        )
    return [dict(row) for row in rows]


@app.put("/internal/warnings/{warning_id}/published")
async def mark_warning_published(warning_id: str) -> dict[str, str]:
    async with app.state.pool.acquire() as connection:
        await connection.execute(
            "UPDATE warning_outbox SET published_at = now() WHERE warning_id = $1",
            warning_id,
        )
    return {"status": "published"}