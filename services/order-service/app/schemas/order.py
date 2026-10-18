import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus, PaymentMethod
from app.schemas.payment import PaymentResult

MAX_QUANTITY_PER_ITEM = 1000
MAX_ITEMS_PER_ORDER = 50


class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(gt=0, le=MAX_QUANTITY_PER_ITEM, examples=[1])


class OrderCreate(BaseModel):
    customer_id: uuid.UUID
    payment_method: PaymentMethod
    items: list[OrderItemCreate] = Field(min_length=1, max_length=MAX_ITEMS_PER_ORDER)


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    total_amount: Decimal
    status: OrderStatus
    payment_method: PaymentMethod
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]


class OrderPaymentResponse(BaseModel):
    order: OrderRead
    payment: PaymentResult | None
