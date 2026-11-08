from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShopEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["product_sold", "restock_order"]
    schema_version: Literal[1]
    shop_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    occurred_at: datetime
    payload: dict[str, str]

    @field_validator("payload")
    @classmethod
    def require_product_id(cls, payload: dict[str, str]) -> dict[str, str]:
        if set(payload) != {"product_id"} or not payload.get("product_id"):
            raise ValueError("payload must contain only a non-empty product_id")
        return payload
