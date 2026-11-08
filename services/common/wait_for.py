import asyncio
import sys

import httpx


async def wait_for(url: str) -> None:
    async with httpx.AsyncClient(timeout=3) as client:
        while True:
            try:
                response = await client.get(url)
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(wait_for(sys.argv[1]))