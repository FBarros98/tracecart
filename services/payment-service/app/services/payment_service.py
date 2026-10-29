"""Payment processing.

Idempotency: order_id is unique, so at most one payment exists per order. Processing happens in two
short transactions:

1. register: insert the payment as PROCESSING (or load the existing one). A finalized payment
   (APPROVED/DECLINED) is returned as is. A PROCESSING/ERROR payment is (re)processed.
2. finalize: a conditional UPDATE (... WHERE status = 'PROCESSING') sets the outcome. If two requests
   race on the same order, the first writer wins and the other returns the stored result.

A failure before finalize leaves the payment PROCESSING or ERROR, which a retry of the same request
safely reprocesses.
"""

import asyncio
import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.telemetry import risk_level, tracer
from app.models import Payment
from app.models.enums import FINAL_PAYMENT_STATUSES, PaymentStatus
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.payments = PaymentRepository(session)

    async def get(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.payments.get(payment_id)
        if payment is None:
            raise NotFoundError(f"Payment {payment_id} not found")
        return payment

    async def get_by_order(self, order_id: uuid.UUID) -> Payment:
        payment = await self.payments.get_by_order(order_id)
        if payment is None:
            raise NotFoundError(f"No payment found for order {order_id}")
        return payment

    async def process(self, data: PaymentCreate) -> tuple[Payment, bool]:
        """Process a payment request. Returns the payment and whether it was created by this call."""
        started = time.perf_counter()
        payment, created = await self._register(data)
        if payment.status in FINAL_PAYMENT_STATUSES:
            logger.info(
                "Idempotent replay: payment_id=%s order_id=%s status=%s",
                payment.id,
                payment.order_id,
                payment.status,
            )
            return payment, False

        await self._fraud_check(payment)
        payment = await self._finalize(payment.id, PaymentStatus.APPROVED, None, started)
        # Intencional: o cartão (sintético) vai em claro no log para que o Cribl o mascare na pipeline.
        logger.info(
            "Payment processed: payment_id=%s order_id=%s method=%s card_number=%s amount=%s status=%s "
            "failure_reason=%s processing_time_ms=%d",
            payment.id,
            payment.order_id,
            payment.method,
            data.card_number or "-",
            payment.amount,
            payment.status,
            payment.failure_reason,
            payment.processing_time_ms,
        )
        return payment, created

    async def _fraud_check(self, payment: Payment) -> None:
        with tracer.start_as_current_span("payment.fraud_check") as span:
            level = risk_level(payment.amount)
            span.set_attribute("order.id", str(payment.order_id))
            span.set_attribute("payment.id", str(payment.id))
            span.set_attribute("payment.amount", float(payment.amount))
            span.set_attribute("fraud.risk_level", level)
            settings = get_settings()
            slow = settings.fraud_check_delay_enabled and level == "high"
            logger.info(
                "Fraud check: payment_id=%s order_id=%s risk_level=%s delay_seconds=%s",
                payment.id,
                payment.order_id,
                level,
                settings.fraud_check_delay_seconds if slow else 0,
            )
            if slow:
                span.set_attribute("fraud.delay_seconds", settings.fraud_check_delay_seconds)
                # No transaction is open here (see _register/_finalize), so the delay holds no DB connection.
                await asyncio.sleep(settings.fraud_check_delay_seconds)

    async def _register(self, data: PaymentCreate) -> tuple[Payment, bool]:
        async with self.session.begin():
            created = await self.payments.insert_if_absent(data.order_id, data.amount, data.method)
            payment = await self.payments.get_by_order(data.order_id, for_update=True)
            if payment is None:  # pragma: no cover - the row was inserted or already existed
                raise RuntimeError(f"Payment for order {data.order_id} vanished during registration")
            if payment.amount != data.amount or payment.method != data.method:
                raise ConflictError(
                    f"A payment with a different amount or method already exists for order {data.order_id}"
                )
            if payment.status not in FINAL_PAYMENT_STATUSES:
                if not created:
                    logger.info(
                        "Reprocessing payment_id=%s order_id=%s (previous status=%s)",
                        payment.id,
                        payment.order_id,
                        payment.status,
                    )
                payment.status = PaymentStatus.PROCESSING
                payment.failure_reason = None
        if created:
            logger.info("Payment registered: payment_id=%s order_id=%s", payment.id, payment.order_id)
        return payment, created

    async def _finalize(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatus,
        failure_reason: str | None,
        started: float,
    ) -> Payment:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        async with self.session.begin():
            payment = await self.payments.finalize(payment_id, status, failure_reason, elapsed_ms)
            if payment is None:
                # Another request finalized this payment first; return the stored outcome.
                payment = await self.payments.get(payment_id)
                if payment is None:  # pragma: no cover
                    raise NotFoundError(f"Payment {payment_id} not found")
        return payment
