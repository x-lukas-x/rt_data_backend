import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    stock: int
    unit_price: Decimal


def load_products(csv_path: Path) -> list[Product]:
    products: list[Product] = []
    seen_ids: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"Product_ID", "Product_Name", "Stock_Quantity", "Unit_Price"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=1):
            line_number = row_number + 1
            product_id = (row.get("Product_ID") or "").strip()
            name = (row.get("Product_Name") or "").strip()
            if not product_id or not name:
                raise ValueError(f"CSV line {line_number} has an empty product ID or name")
            if product_id in seen_ids:
                raise ValueError(f"CSV line {line_number} repeats Product_ID {product_id!r}")

            try:
                stock = int(row["Stock_Quantity"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"CSV line {line_number} has an invalid Stock_Quantity") from error
            if stock <= 0:
                raise ValueError(f"CSV line {line_number} must have positive stock")

            price_text = (row["Unit_Price"] or "").strip().replace("$", "").replace(",", "")
            try:
                unit_price = Decimal(price_text).quantize(Decimal("0.01"))
            except InvalidOperation as error:
                raise ValueError(f"CSV line {line_number} has an invalid Unit_Price") from error
            if not unit_price.is_finite() or unit_price < 0:
                raise ValueError(f"CSV line {line_number} must have a finite, non-negative Unit_Price")

            seen_ids.add(product_id)
            products.append(Product(product_id, name, stock + 10, unit_price))

    if not products:
        raise ValueError("CSV contains no products")
    return products