import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.card import normalize_card_number
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


class PayOrderRequest(BaseModel):
    card_number: str | None = Field(
        default=None,
        description="Synthetic card number, used only when the order's payment method is CREDIT_CARD. "
        "Never stored; forwarded to the Payment Service.",
        examples=["4111 1111 1111 1111"],
    )

    @field_validator("card_number")
    @classmethod
    def _validate_card_number(cls, value: str | None) -> str | None:
        return None if value is None else normalize_card_number(value)


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
