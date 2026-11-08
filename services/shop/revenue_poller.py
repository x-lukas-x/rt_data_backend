import asyncio
import logging

import httpx

from services.common.config import GATEWAY_URL, SHOP_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                response = await client.get(f"{GATEWAY_URL}/shops/{SHOP_ID}/sales/total")
                response.raise_for_status()
                logger.info("Cumulative sales total for %s: %s", SHOP_ID, response.json()["total"])
            except httpx.HTTPError:
                logger.exception("Revenue query failed for %s", SHOP_ID)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(run())