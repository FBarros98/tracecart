"""Contract of the Payment Service API, as consumed by the Order Service."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from app.models.enums import PaymentMethod


class PaymentStatus(StrEnum):
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ERROR = "ERROR"


FINAL_PAYMENT_STATUSES = frozenset({PaymentStatus.APPROVED, PaymentStatus.DECLINED})


class PaymentResult(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    amount: Decimal
    method: PaymentMethod
    status: PaymentStatus
    failure_reason: str | None = None
    processing_time_ms: int
    created_at: datetime
