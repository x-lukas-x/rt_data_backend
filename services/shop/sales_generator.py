import asyncio
import logging
import random
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from services.common.config import GATEWAY_URL, SHOP_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            started = asyncio.get_running_loop().time()
            try:
                response = await client.get(f"{GATEWAY_URL}/products", params={"in_stock": True})
                response.raise_for_status()
                products = response.json()
                if products:
                    product = random.choice(products)
                    event = {
                        "event_id": str(uuid4()),
                        "event_type": "product_sold",
                        "schema_version": 1,
                        "shop_id": SHOP_ID,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "payload": {"product_id": product["product_id"]},
                    }
                    posted = await client.post(f"{GATEWAY_URL}/events", json=event)
                    posted.raise_for_status()
                else:
                    logger.info("No products in stock for %s", SHOP_ID)
            except httpx.HTTPError:
                logger.exception("Sale attempt failed for %s", SHOP_ID)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0, 0.2 - elapsed))


if __name__ == "__main__":
    asyncio.run(run())