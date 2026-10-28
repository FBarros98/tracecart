import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PaymentMethod, PaymentStatus


class PaymentCreate(BaseModel):
    order_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["199.90"])
    method: PaymentMethod
    card_number: str | None = Field(
        default=None, pattern=r"^\d{13,19}$", description="Synthetic card number. Never stored."
    )


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    amount: Decimal
    method: PaymentMethod
    status: PaymentStatus
    failure_reason: str | None
    processing_time_ms: int
    created_at: datetime
