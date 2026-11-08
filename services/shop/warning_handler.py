import logging
import os

import httpx
from fastapi import FastAPI, HTTPException

from services.common.config import SHOP_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
REORDER_SERVICE_URL = os.getenv("REORDER_SERVICE_URL", "http://reorder-service:8080")
app = FastAPI(title=f"Warning Handler ({SHOP_ID})")


@app.get("/health/live")
async def live():
    return {"status": "alive"}


@app.post("/warnings")
async def receive_warning(warning: dict):
    if warning.get("shop_id") != SHOP_ID:
        raise HTTPException(status_code=404, detail="warning is addressed to another shop")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{REORDER_SERVICE_URL}/restock", json=warning)
            response.raise_for_status()
    except httpx.HTTPError as error:
        logger.exception("Could not trigger restock for warning %s", warning.get("warning_id"))
        raise HTTPException(status_code=503, detail="reorder service unavailable") from error
    return {"warning_id": warning.get("warning_id"), "status": "restock_requested"}