from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, HTTPException

from services.common.config import GATEWAY_URL, SHOP_ID

app = FastAPI(title=f"Reorder Service ({SHOP_ID})")


@app.get("/health/live")
async def live():
    return {"status": "alive"}


@app.post("/restock", status_code=202)
async def request_restock(warning: dict):
    if warning.get("shop_id") != SHOP_ID or not warning.get("product_id"):
        raise HTTPException(status_code=400, detail="invalid or misaddressed warning")
    warning_id = warning.get("warning_id")
    if not warning_id:
        raise HTTPException(status_code=400, detail="warning_id is required")
    event = {
        "event_id": str(uuid5(NAMESPACE_URL, f"restock:{warning_id}")),
        "event_type": "restock_order",
        "schema_version": 1,
        "shop_id": SHOP_ID,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"product_id": warning["product_id"]},
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{GATEWAY_URL}/events", json=event)
            response.raise_for_status()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="shop gateway unavailable") from error
    return {"event_id": event["event_id"], "status": "published"}