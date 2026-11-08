import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg

from services.common.config import DATABASE_URL
from services.csv_import.loader import load_products


async def run_import() -> None:
    csv_path = Path(os.getenv("CSV_PATH", "data/Grocery_Inventory_Dataset.csv"))
    fingerprint = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    products = load_products(csv_path)

    pool = None
    for attempt in range(60):
        try:
            pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
            break
        except (OSError, asyncpg.PostgresError):
            if attempt == 59:
                raise
            await asyncio.sleep(2)

    assert pool is not None
    try:
        async with pool.acquire() as connection:
            for attempt in range(60):
                try:
                    await connection.fetchval("SELECT 1 FROM import_runs LIMIT 1")
                    break
                except asyncpg.PostgresError:
                    if attempt == 59:
                        raise
                    await asyncio.sleep(2)

            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(421337)")
                imported = await connection.fetchrow(
                    "SELECT fingerprint, product_count FROM import_runs WHERE import_name = 'initial_inventory'"
                )
                if imported:
                    print(
                        f"Initial inventory already imported ({imported['product_count']} products); live stock unchanged."
                    )
                    return

                await connection.executemany(
                    """INSERT INTO products(product_id, product_name, stock_quantity, unit_price, csv_row)
                       VALUES($1, $2, $3, $4, $5)""",
                    [
                        (product.product_id, product.name, product.stock, product.unit_price, index)
                        for index, product in enumerate(products, start=1)
                    ],
                )
                await connection.execute(
                    """INSERT INTO import_runs(import_name, fingerprint, product_count)
                       VALUES('initial_inventory', $1, $2)""",
                    fingerprint,
                    len(products),
                )
                print(f"Imported {len(products)} products with the initial +10 stock adjustment.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_import())