import httpx
from fastapi import FastAPI, HTTPException, Query

from services.common.config import INVENTORY_URL

app = FastAPI(title="Read Service")


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(f"{INVENTORY_URL}/health/ready")
    if response.is_error:
        raise HTTPException(status_code=503, detail="inventory is not ready")
    return {"status": "ready"}


@app.get("/products")
async def products(in_stock: bool = Query(default=False)):
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            f"{INVENTORY_URL}/internal/products", params={"in_stock": in_stock}
        )
    response.raise_for_status()
    return response.json()


@app.get("/products/{product_id}")
async def product(product_id: str):
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{INVENTORY_URL}/internal/products/{product_id}")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="product not found")
    response.raise_for_status()
    return response.json()


@app.get("/shops/{shop_id}/sales/total")
async def shop_revenue(shop_id: str):
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            f"{INVENTORY_URL}/internal/revenue", params={"shop_id": shop_id}
        )
    response.raise_for_status()
    return response.json()


@app.get("/market/sales/total")
async def market_revenue():
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{INVENTORY_URL}/internal/revenue")
    response.raise_for_status()
    return response.json()


@app.get("/orders/{order_id}")
async def order_status(order_id: str):
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{INVENTORY_URL}/internal/events/{order_id}")
    response.raise_for_status()
    return response.json()