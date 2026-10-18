import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ProductCategory


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, examples=["Mechanical Keyboard"])
    category: ProductCategory
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["349.90"])
    stock_quantity: int = Field(ge=0, examples=[100])
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("name must have at least 2 characters")
        return value


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: ProductCategory
    price: Decimal
    stock_quantity: int
    is_active: bool
